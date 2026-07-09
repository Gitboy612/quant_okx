# -*- coding: utf-8 -*-
"""QuantOKX 桌面客户端 QML↔Python 桥接层（Task 2）

设计要点
--------
- 复用后端模型层与服务层，**不重构 FastAPI routers**：
  * 数据读取：直接用 ``backend/database.py`` 的 ``SessionLocal`` 查 SQLAlchemy 模型，
    返回 ``QVariantList``（list[dict]）给 QML，QML 端按 JS 对象访问。
  * 业务写操作：调用 ``backend/services/`` 里的服务（order_manager / strategy_engine 等），
    本任务仅暴露读接口与认证，写接口留给 Task 5 接服务层。
- 认证：``AuthService.login`` 调 ``auth_service`` 验证密码并签发 JWT，token 存内存；
  后续读接口目前**不强制鉴权**（桌面端单用户同进程，与 routers 的 Depends 解耦），
  Task 5 视需要再在写接口里校验 token。
- 主动推送信号：每个服务定义 Qt signals（``orderFilled`` / ``strategyTriggered`` / ``alert`` 等），
  本任务只定义不接，Task 5 再连 ``order_manager`` / ``strategy_engine`` 的事件。
- 注册方式：``qmlRegisterType`` 显式注册到 QML 模块 ``QuantOKX.Services 1.0``。
  （注：``@QmlElement`` 在当前 PySide6 6.11 构建中读取 ``QML_IMPORT_NAME`` 类属性存在兼容性问题，
  改用 ``qmlRegisterType`` 同样达到「QML 端 import 后实例化」的效果，且更显式可控。）
- 数据库 Session 一律 ``try/finally`` 关闭，避免连接泄漏。

QML 端用法（Task 4 接入时）::

    import QuantOKX.Services 1.0
    ApplicationWindow {
        AccountService { id: accountSvc }
        Component.onCompleted: console.log(JSON.stringify(accountSvc.listAccounts()))
    }

为方便 Task 4 不实例化也能用 + 便于 main.py 连信号，main.py 还会通过
``engine.rootContext().setContextProperty`` 暴露单例实例（见 main.py）。
"""

import os
import sys
from datetime import datetime, timezone, timedelta

# 让 backend 包可被 import（backend 内部用绝对 import 如 `from database import ...`、
# `from models.account import Account`，因此需把 backend 目录本身加入 sys.path）
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtQml import qmlRegisterType

# ---- 后端模型 / 服务 / 工具（绝对 import，依赖上面注入的 sys.path）----
from database import SessionLocal  # noqa: E402
from models.account import Account  # noqa: E402
from models.order import Order  # noqa: E402
from models.strategy import StrategyTemplate, StrategyInstance  # noqa: E402
from models.pnl import PnlRecord  # noqa: E402
from models.log import OperationLog  # noqa: E402
from models.api_call_log import ApiCallLog  # noqa: E402
from models.strategy_event import StrategyEvent  # noqa: E402
from models.user import User  # noqa: E402
from services.auth_service import verify_password, create_access_token  # noqa: E402
from config import LOGIN_MAX_ATTEMPTS, LOGIN_LOCKOUT_MINUTES  # noqa: E402

# QML 模块 URI（Task 4 在 QML 中 `import QuantOKX.Services 1.0`）
QML_MODULE_URI = "QuantOKX.Services"
QML_MODULE_MAJOR = 1
QML_MODULE_MINOR = 0


# ###############################################################################
# 工具函数
# ###############################################################################

def _dt(value):
    """datetime → ISO 字符串；None 保留 None（QML 端按 null 处理）。"""
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return None


def _mask_key(key: str) -> str:
    """API Key 脱敏，与后端 routers/accounts.py 的 _mask_key 保持一致。"""
    if not key:
        return "****"
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


# ###############################################################################
# 服务基类
# ###############################################################################

class BaseService(QObject):
    """所有桥接服务的基类：提供通用 ``alert(title, body)`` 主动推送信号。

    子类按需再定义各自业务信号（如 OrderService.orderFilled）。
    """

    # 通用告警信号：参数 (title, body)，均为字符串
    alert = Signal(str, str)


# ###############################################################################
# 账户服务
# ###############################################################################

class AccountService(BaseService):
    """账户查询服务。只返回脱敏后的字段，绝不把加密密钥泄露给 QML。"""

    @Slot(result="QVariantList")
    def listAccounts(self):
        """返回全部账户（脱敏）。对应 GET /api/accounts。"""
        db = SessionLocal()
        try:
            accounts = db.query(Account).all()
            return [self._to_dict(a) for a in accounts]
        finally:
            db.close()

    @Slot(int, result="QVariant")
    def getAccount(self, account_id):
        """返回单个账户（脱敏）；不存在返回空 dict。"""
        db = SessionLocal()
        try:
            acc = db.query(Account).filter(Account.id == account_id).first()
            return self._to_dict(acc) if acc else {}
        finally:
            db.close()

    @staticmethod
    def _to_dict(acc: Account) -> dict:
        # 与 routers/accounts.py 的 _account_to_response 字段保持一致
        return {
            "id": acc.id,
            "name": acc.name,
            "trade_mode": acc.trade_mode,
            "exchange": acc.exchange,
            "is_active": bool(acc.is_active),
            "api_key_masked": _mask_key(acc.api_key_encrypted[:16]) if acc.api_key_encrypted else "****",
            "created_at": _dt(acc.created_at),
        }


# ###############################################################################
# 策略服务
# ###############################################################################

class StrategyService(BaseService):
    """策略模板 / 实例查询服务。"""

    # 策略触发事件信号：参数为事件 dict（Task 5 接 strategy_engine）
    strategyTriggered = Signal("QVariant")
    # 策略状态变更信号：参数为实例 dict
    strategyStatusChanged = Signal("QVariant")

    @Slot(result="QVariantList")
    def listTemplates(self):
        """返回全部策略模板。对应 GET /api/strategies/templates。"""
        db = SessionLocal()
        try:
            templates = db.query(StrategyTemplate).all()
            return [
                {
                    "id": t.id,
                    "name": t.name,
                    "strategy_type": t.strategy_type,
                    "description": t.description,
                    "default_params": t.default_params,
                    "param_schema": t.param_schema,
                    "is_builtin": bool(t.is_builtin),
                    "is_custom": bool(t.is_custom),
                    "dsl_config": t.dsl_config,
                }
                for t in templates
            ]
        finally:
            db.close()

    @Slot(result="QVariantList")
    def listInstances(self):
        """返回全部策略实例（含模板名 / 类型，通过 join）。对应 GET /api/strategies/instances。"""
        db = SessionLocal()
        try:
            rows = (
                db.query(StrategyInstance, StrategyTemplate)
                .join(StrategyTemplate, StrategyInstance.template_id == StrategyTemplate.id, isouter=True)
                .order_by(StrategyInstance.created_at.desc())
                .all()
            )
            return [
                {
                    "id": inst.id,
                    "template_id": inst.template_id,
                    "template_name": tpl.name if tpl else "",
                    "strategy_type": tpl.strategy_type if tpl else "",
                    "account_id": inst.account_id,
                    "name": inst.name,
                    "symbol": inst.symbol,
                    "market_type": inst.market_type,
                    "params": inst.params,
                    "status": inst.status,
                    "started_at": _dt(inst.started_at),
                    "stopped_at": _dt(inst.stopped_at),
                    "created_at": _dt(inst.created_at),
                    "updated_at": _dt(inst.updated_at),
                }
                for inst, tpl in rows
            ]
        finally:
            db.close()

    @Slot(int, result="QVariant")
    def getInstance(self, instance_id):
        """返回单个策略实例（含模板名）。"""
        db = SessionLocal()
        try:
            row = (
                db.query(StrategyInstance, StrategyTemplate)
                .join(StrategyTemplate, StrategyInstance.template_id == StrategyTemplate.id, isouter=True)
                .filter(StrategyInstance.id == instance_id)
                .first()
            )
            if not row:
                return {}
            inst, tpl = row
            return {
                "id": inst.id,
                "template_id": inst.template_id,
                "template_name": tpl.name if tpl else "",
                "strategy_type": tpl.strategy_type if tpl else "",
                "account_id": inst.account_id,
                "name": inst.name,
                "symbol": inst.symbol,
                "market_type": inst.market_type,
                "params": inst.params,
                "status": inst.status,
                "started_at": _dt(inst.started_at),
                "stopped_at": _dt(inst.stopped_at),
                "created_at": _dt(inst.created_at),
                "updated_at": _dt(inst.updated_at),
            }
        finally:
            db.close()


# ###############################################################################
# 订单服务
# ###############################################################################

class OrderService(BaseService):
    """订单查询服务。

    说明：PySide6 同名 ``@Slot`` 重载在 Python 端会被后定义者覆盖（按参数个数分派
    仅在 QML 侧且不可靠），故每个查询提供**唯一方法名**，Python / QML 双端均可调用。
    """

    # 订单成交信号：参数为订单 dict（Task 5 接 order_manager）
    orderFilled = Signal("QVariant")

    @Slot(result="QVariantList")
    def listOrders(self):
        """返回最近 100 条订单（全部账户）。对应 GET /api/orders（无过滤）。"""
        return self._query(None, 100)

    @Slot(int, result="QVariantList")
    def listOrdersWithLimit(self, limit):
        """返回最近 ``limit`` 条订单（全部账户）。"""
        return self._query(None, limit)

    @Slot(int, result="QVariantList")
    def listOrdersByAccount(self, account_id):
        """按账户返回最近 100 条订单。"""
        return self._query(account_id, 100)

    @Slot(int, int, result="QVariantList")
    def listOrdersByAccountWithLimit(self, account_id, limit):
        """按账户 + 数量返回订单。"""
        return self._query(account_id, limit)

    @staticmethod
    def _to_dict(o: Order) -> dict:
        return {
            "id": o.id,
            "strategy_instance_id": o.strategy_instance_id,
            "account_id": o.account_id,
            "symbol": o.symbol,
            "order_id": o.order_id,
            "cl_ord_id": o.cl_ord_id,
            "side": o.side,
            "order_type": o.order_type,
            "price": o.price,
            "quantity": o.quantity,
            "filled_quantity": o.filled_quantity,
            "state": o.state,
            "fill_px": o.fill_px,
            "fill_sz": o.fill_sz,
            "fee": o.fee,
            "update_time": o.update_time,
            "status": o.status,
            "created_at": _dt(o.created_at),
            "updated_at": _dt(o.updated_at),
        }

    def _query(self, account_id, limit):
        db = SessionLocal()
        try:
            query = db.query(Order)
            if account_id is not None:
                query = query.filter(Order.account_id == account_id)
            orders = query.order_by(Order.created_at.desc()).limit(limit).all()
            return [self._to_dict(o) for o in orders]
        finally:
            db.close()


# ###############################################################################
# 盈亏服务
# ###############################################################################

class PnlService(BaseService):
    """盈亏记录查询服务。

    说明：同名 ``@Slot`` 重载在 Python 端会覆盖，故用唯一方法名（见 OrderService 说明）。
    """

    @Slot(result="QVariantList")
    def listPnl(self):
        """返回最近 100 条盈亏记录。对应 GET /api/pnl。"""
        return self._query(None, 100)

    @Slot(int, result="QVariantList")
    def listPnlWithLimit(self, limit):
        """返回最近 ``limit`` 条盈亏记录。"""
        return self._query(None, limit)

    @Slot(int, result="QVariantList")
    def listPnlByAccount(self, account_id):
        """按账户返回最近 100 条盈亏记录。"""
        return self._query(account_id, 100)

    @Slot(int, int, result="QVariantList")
    def listPnlByAccountWithLimit(self, account_id, limit):
        """按账户 + 数量返回盈亏记录。"""
        return self._query(account_id, limit)

    @Slot(result="QVariant")
    def summary(self):
        """盈亏汇总。对应 GET /api/pnl/summary（取最近 500 条聚合）。"""
        db = SessionLocal()
        try:
            records = (
                db.query(PnlRecord)
                .order_by(PnlRecord.recorded_at.desc())
                .limit(500)
                .all()
            )
            if not records:
                return {
                    "total_realized_pnl": 0,
                    "total_unrealized_pnl": 0,
                    "total_pnl": 0,
                    "latest_equity": 0,
                }
            latest = records[0]
            total_realized = latest.realized_pnl or 0
            return {
                "total_realized_pnl": total_realized,
                "total_unrealized_pnl": latest.unrealized_pnl or 0,
                "total_pnl": total_realized + (latest.unrealized_pnl or 0),
                "latest_equity": latest.equity or 0,
            }
        finally:
            db.close()

    @staticmethod
    def _to_dict(r: PnlRecord) -> dict:
        return {
            "id": r.id,
            "account_id": r.account_id,
            "strategy_instance_id": r.strategy_instance_id,
            "equity": r.equity,
            "unrealized_pnl": r.unrealized_pnl,
            "realized_pnl": r.realized_pnl,
            "total_pnl": r.total_pnl,
            "recorded_at": _dt(r.recorded_at),
        }

    def _query(self, account_id, limit):
        db = SessionLocal()
        try:
            query = db.query(PnlRecord)
            if account_id is not None:
                query = query.filter(PnlRecord.account_id == account_id)
            records = query.order_by(PnlRecord.recorded_at.desc()).limit(limit).all()
            return [self._to_dict(r) for r in records]
        finally:
            db.close()


# ###############################################################################
# 监控服务（策略事件）
# ###############################################################################

class MonitoringService(BaseService):
    """监控服务：查询策略事件（StrategyEvent）。

    对应后端 routers/monitoring.py，该路由操作的是 ``models.strategy_event.StrategyEvent``。
    说明：同名 ``@Slot`` 重载在 Python 端会覆盖，故用唯一方法名（见 OrderService 说明）。
    """

    @Slot(int, result="QVariantList")
    def listEvents(self, strategy_id):
        """返回某策略实例最近 100 条事件。对应 GET /api/monitoring/strategy/{id}/events。"""
        return self._query(strategy_id, 100, None)

    @Slot(int, int, result="QVariantList")
    def listEventsWithLimit(self, strategy_id, limit):
        """按数量返回某策略实例事件。"""
        return self._query(strategy_id, limit, None)

    @Slot(int, int, str, result="QVariantList")
    def listEventsByType(self, strategy_id, limit, event_type):
        """按数量 + 事件类型过滤返回事件。"""
        return self._query(strategy_id, limit, event_type)

    @Slot(int, result="QVariant")
    def eventStats(self, strategy_id):
        """返回某策略事件总数 + 按 event_type 计数。"""
        db = SessionLocal()
        try:
            base = db.query(StrategyEvent).filter(
                StrategyEvent.strategy_instance_id == strategy_id
            )
            total = base.count()
            # 按 event_type 分组计数
            from sqlalchemy import func
            grouped = (
                db.query(StrategyEvent.event_type, func.count(StrategyEvent.id))
                .filter(StrategyEvent.strategy_instance_id == strategy_id)
                .group_by(StrategyEvent.event_type)
                .all()
            )
            return {
                "total": total,
                "by_type": {et: cnt for et, cnt in grouped},
            }
        finally:
            db.close()

    @staticmethod
    def _event_to_dict(e: StrategyEvent) -> dict:
        return {
            "id": e.id,
            "strategy_instance_id": e.strategy_instance_id,
            "event_type": e.event_type,
            "message": e.message,
            "details": e.details,
            "created_at": _dt(e.created_at),
        }

    def _query(self, strategy_id, limit, event_type):
        db = SessionLocal()
        try:
            query = db.query(StrategyEvent).filter(
                StrategyEvent.strategy_instance_id == strategy_id
            )
            if event_type:
                query = query.filter(StrategyEvent.event_type == event_type)
            events = query.order_by(StrategyEvent.created_at.desc()).limit(limit).all()
            return [self._event_to_dict(e) for e in events]
        finally:
            db.close()


# ###############################################################################
# 日志服务（操作日志 + API 调用日志）
# ###############################################################################

class LogService(BaseService):
    """日志查询服务。

    说明：同名 ``@Slot`` 重载在 Python 端会覆盖，故用唯一方法名（见 OrderService 说明）。
    """

    # ---- 操作日志（OperationLog）----
    @Slot(result="QVariantList")
    def listLogs(self):
        """返回最近 100 条操作日志。对应 GET /api/logs。"""
        return self._query_logs(100, None, None)

    @Slot(int, result="QVariantList")
    def listLogsWithLimit(self, limit):
        """返回最近 ``limit`` 条操作日志。"""
        return self._query_logs(limit, None, None)

    @Slot(str, result="QVariantList")
    def listLogsByAction(self, action):
        """按 action 过滤返回最近 100 条操作日志。"""
        return self._query_logs(100, action, None)

    @Slot(str, int, result="QVariantList")
    def listLogsByActionWithLimit(self, action, limit):
        """按 action + 数量返回操作日志。"""
        return self._query_logs(limit, action, None)

    # ---- API 调用日志（ApiCallLog）----
    @Slot(result="QVariantList")
    def listApiLogs(self):
        """返回最近 100 条 API 调用日志。对应 GET /api/strategies/api-call-logs。"""
        return self._query_api_logs(None, 100)

    @Slot(int, result="QVariantList")
    def listApiLogsWithLimit(self, limit):
        """返回最近 ``limit`` 条 API 调用日志。"""
        return self._query_api_logs(None, limit)

    @Slot(int, result="QVariantList")
    def listApiLogsByStrategy(self, strategy_instance_id):
        """按策略实例返回最近 100 条 API 调用日志。"""
        return self._query_api_logs(strategy_instance_id, 100)

    @Slot(int, int, result="QVariantList")
    def listApiLogsByStrategyWithLimit(self, strategy_instance_id, limit):
        """按策略实例 + 数量返回 API 调用日志。"""
        return self._query_api_logs(strategy_instance_id, limit)

    @staticmethod
    def _log_to_dict(l: OperationLog) -> dict:
        return {
            "id": l.id,
            "user_id": l.user_id,
            "action": l.action,
            "target_type": l.target_type,
            "target_id": l.target_id,
            "detail": l.detail,
            "ip_address": l.ip_address,
            "created_at": _dt(l.created_at),
        }

    @staticmethod
    def _api_log_to_dict(l: ApiCallLog) -> dict:
        return {
            "id": l.id,
            "strategy_instance_id": l.strategy_instance_id,
            "account_name": l.account_name,
            "endpoint": l.endpoint,
            "method": l.method,
            "request_body": l.request_body,
            "response_code": l.response_code,
            "response_body": l.response_body,
            "status": l.status,
            "created_at": _dt(l.created_at),
        }

    def _query_logs(self, limit, action, target_type):
        db = SessionLocal()
        try:
            query = db.query(OperationLog)
            if action:
                query = query.filter(OperationLog.action == action)
            if target_type:
                query = query.filter(OperationLog.target_type == target_type)
            logs = query.order_by(OperationLog.created_at.desc()).limit(limit).all()
            return [self._log_to_dict(l) for l in logs]
        finally:
            db.close()

    def _query_api_logs(self, strategy_instance_id, limit):
        db = SessionLocal()
        try:
            query = db.query(ApiCallLog)
            if strategy_instance_id is not None:
                query = query.filter(ApiCallLog.strategy_instance_id == strategy_instance_id)
            logs = query.order_by(ApiCallLog.created_at.desc()).limit(limit).all()
            return [self._api_log_to_dict(l) for l in logs]
        finally:
            db.close()


# ###############################################################################
# 认证服务
# ###############################################################################

class AuthService(BaseService):
    """认证服务：登录验签 + 签发 JWT，token / 当前用户存内存。

    说明：桌面端同进程单用户，读接口不强制鉴权；登录成功后写一条 OperationLog
    （ip_address 记为 "desktop"），与后端 routers/auth.py 行为对齐。
    """

    # 登录状态变更信号：参数为是否已登录
    authChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token = ""        # JWT，登录成功后赋值
        self._user_id = None    # 当前用户 id
        self._username = ""     # 当前用户名

    @Slot(str, str, result="QString")
    def login(self, username, password):
        """登录验证。成功返回 JWT token 字符串；失败返回空字符串。

        复刻 routers/auth.py 的逻辑：账户锁定检查 → 密码校验 → 失败累计锁定 →
        成功重置尝试次数 → 写 OperationLog → 签发 token。
        """
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                return ""

            # 账户锁定检查
            if user.locked_until and user.locked_until > datetime.now(timezone.utc):
                return ""

            if not verify_password(password, user.password_hash):
                user.login_attempts = (user.login_attempts or 0) + 1
                if user.login_attempts >= LOGIN_MAX_ATTEMPTS:
                    user.locked_until = datetime.now(timezone.utc) + timedelta(
                        minutes=LOGIN_LOCKOUT_MINUTES
                    )
                db.commit()
                return ""

            # 登录成功
            user.login_attempts = 0
            user.locked_until = None
            db.commit()

            # 写操作日志
            log = OperationLog(
                user_id=user.id,
                action="login",
                target_type="system",
                ip_address="desktop",
            )
            db.add(log)
            db.commit()

            token = create_access_token({"sub": str(user.id), "username": user.username})
            self._token = token
            self._user_id = user.id
            self._username = user.username
            self.authChanged.emit(True)
            return token
        finally:
            db.close()

    @Slot(result=None)
    def logout(self):
        """退出登录，清空内存中的 token / 用户。"""
        self._token = ""
        self._user_id = None
        self._username = ""
        self.authChanged.emit(False)

    @Slot(result="bool")
    def isAuthenticated(self):
        """是否已登录（内存中有 token）。"""
        return bool(self._token)

    @Slot(result="QVariant")
    def currentUser(self):
        """返回当前用户 dict {id, username}；未登录返回空 dict。"""
        if not self._user_id:
            return {}
        return {"id": self._user_id, "username": self._username}

    @Slot(result="QString")
    def token(self):
        """返回当前 JWT token（未登录返回空串）。供需要走 HTTP 的场景使用。"""
        return self._token


# ###############################################################################
# 注册入口
# ###############################################################################

def register_qml_types():
    """把所有桥接服务注册到 QML 模块 ``QuantOKX.Services 1.0``。

    必须在 ``QQmlApplicationEngine.load(...)`` 之前调用（main.py 已在引擎创建后、
    加载前调用）。注册后 QML 端可 ``import QuantOKX.Services 1.0`` 并实例化各服务。
    """
    qmlRegisterType(AccountService, QML_MODULE_URI, QML_MODULE_MAJOR, QML_MODULE_MINOR, "AccountService")
    qmlRegisterType(StrategyService, QML_MODULE_URI, QML_MODULE_MAJOR, QML_MODULE_MINOR, "StrategyService")
    qmlRegisterType(OrderService, QML_MODULE_URI, QML_MODULE_MAJOR, QML_MODULE_MINOR, "OrderService")
    qmlRegisterType(PnlService, QML_MODULE_URI, QML_MODULE_MAJOR, QML_MODULE_MINOR, "PnlService")
    qmlRegisterType(MonitoringService, QML_MODULE_URI, QML_MODULE_MAJOR, QML_MODULE_MINOR, "MonitoringService")
    qmlRegisterType(LogService, QML_MODULE_URI, QML_MODULE_MAJOR, QML_MODULE_MINOR, "LogService")
    qmlRegisterType(AuthService, QML_MODULE_URI, QML_MODULE_MAJOR, QML_MODULE_MINOR, "AuthService")


# 模块导入即注册：main.py `import qml_bridge` 时自动执行注册，
# 这样即使 main.py 忘记显式调用 register_qml_types() 也已生效。
register_qml_types()
