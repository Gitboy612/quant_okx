"""多渠道告警通知服务。

支持渠道：
- EmailChannel: 基于 smtplib 发送 HTML 邮件（同步 SMTP 包在 asyncio.to_thread 中执行）
- WebhookChannel: 基于 httpx 异步 POST JSON
- TelegramChannel: 基于 httpx 调用 Bot API

NotificationService 是单例：
- init_channels(config) 启动时根据系统配置加载默认渠道
- notify(event_type, title, message, details) 从 DB 规则匹配 event_type，分发给所有匹配渠道
- test_channel(channel_type) 测试单渠道连通性

设计要点：
- 所有 send 方法为 async，不阻塞策略主循环
- 异常被捕获并打印，绝不向上抛出（通知失败不应影响业务）
- DB 规则在每次 notify 时按需查询，保证规则变更立即生效
"""
from __future__ import annotations

import smtplib
import asyncio
import hashlib
import hmac
import json
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any

import httpx


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------

class NotificationChannel(ABC):
    """通知渠道抽象基类。"""

    channel_type: str = "abstract"

    @abstractmethod
    async def send(self, title: str, message: str, details: dict) -> bool:
        """发送通知。返回 True 表示成功，False 表示失败。"""
        ...


# ---------------------------------------------------------------------------
# EmailChannel
# ---------------------------------------------------------------------------

class EmailChannel(NotificationChannel):
    """基于 smtplib 的邮件渠道。

    配置字段：
        smtp_host: SMTP 服务器地址
        smtp_port: SMTP 端口
        smtp_user: 登录用户名
        smtp_password: 登录密码
        from_email: 发件人地址
        to_emails: 收件人列表（逗号分隔字符串或 list）
    """

    channel_type = "email"

    def __init__(self, config: dict):
        self.smtp_host = str(config.get("smtp_host", ""))
        self.smtp_port = int(config.get("smtp_port", 465))
        self.smtp_user = str(config.get("smtp_user", ""))
        self.smtp_password = str(config.get("smtp_password", ""))
        self.from_email = str(config.get("from_email", self.smtp_user))
        to = config.get("to_emails", [])
        if isinstance(to, str):
            self.to_emails = [e.strip() for e in to.split(",") if e.strip()]
        else:
            self.to_emails = [str(e) for e in to]

    def _build_message(self, title: str, message: str, details: dict) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = title
        msg["From"] = self.from_email
        msg["To"] = ", ".join(self.to_emails)

        # 纯文本兜底
        text_part = MIMEText(message, "plain", "utf-8")
        msg.attach(text_part)

        # HTML 正文
        details_html = ""
        if details:
            try:
                details_html = (
                    '<hr style="border:none;border-top:1px solid #eee;margin:16px 0;">'
                    '<pre style="font-size:12px;color:#666;white-space:pre-wrap;">'
                    f'{json.dumps(details, ensure_ascii=False, indent=2)}</pre>'
                )
            except Exception:
                details_html = f"<pre>{details}</pre>"

        html = f"""
        <html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#333;max-width:600px;margin:0 auto;padding:20px;">
            <h2 style="color:#00D4AA;margin:0 0 12px;">{title}</h2>
            <p style="font-size:14px;line-height:1.6;margin:0 0 8px;">{message}</p>
            {details_html}
            <hr style="border:none;border-top:1px solid #eee;margin:16px 0;">
            <p style="font-size:11px;color:#999;">QuantOKX 量化交易平台 · 自动告警</p>
        </body></html>
        """
        html_part = MIMEText(html, "html", "utf-8")
        msg.attach(html_part)
        return msg

    def _send_sync(self, title: str, message: str, details: dict) -> bool:
        if not self.smtp_host or not self.to_emails:
            print("[EmailChannel] 缺少 smtp_host 或 to_emails 配置")
            return False
        try:
            msg = self._build_message(title, message, details)
            # 465 端口使用 SMTP_SSL，其余使用 SMTP + starttls
            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15) as server:
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_email, self.to_emails, msg.as_string())
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                    server.ehlo()
                    try:
                        server.starttls()
                        server.ehlo()
                    except smtplib.SMTPException:
                        pass  # 服务端不支持 TLS 时跳过
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_email, self.to_emails, msg.as_string())
            return True
        except Exception as e:
            print(f"[EmailChannel] 发送失败: {e}")
            return False

    async def send(self, title: str, message: str, details: dict) -> bool:
        # smtplib 为同步阻塞调用，用 to_thread 包装避免阻塞事件循环
        return await asyncio.to_thread(self._send_sync, title, message, details)


# ---------------------------------------------------------------------------
# WebhookChannel
# ---------------------------------------------------------------------------

class WebhookChannel(NotificationChannel):
    """基于 httpx 的 Webhook 渠道。

    配置字段：
        webhook_url: 目标 URL
        secret: 可选签名密钥（计算 HMAC-SHA256 放入 X-Signature 头）
    """

    channel_type = "webhook"

    def __init__(self, config: dict):
        self.webhook_url = str(config.get("webhook_url", ""))
        self.secret = str(config.get("secret", "")) or None

    async def send(self, title: str, message: str, details: dict) -> bool:
        if not self.webhook_url:
            print("[WebhookChannel] 缺少 webhook_url 配置")
            return False
        payload: dict[str, Any] = {
            "title": title,
            "message": message,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        headers = {"Content-Type": "application/json"}
        if self.secret:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            sig = hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            headers["X-Signature"] = sig
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(self.webhook_url, json=payload, headers=headers)
            return 200 <= resp.status_code < 300
        except Exception as e:
            print(f"[WebhookChannel] 发送失败: {e}")
            return False


# ---------------------------------------------------------------------------
# TelegramChannel
# ---------------------------------------------------------------------------

class TelegramChannel(NotificationChannel):
    """基于 httpx 的 Telegram Bot 渠道。

    配置字段：
        bot_token: Bot API Token
        chat_id: 目标 chat_id
    """

    channel_type = "telegram"
    API_BASE = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, config: dict):
        self.bot_token = str(config.get("bot_token", ""))
        self.chat_id = str(config.get("chat_id", ""))

    async def send(self, title: str, message: str, details: dict) -> bool:
        if not self.bot_token or not self.chat_id:
            print("[TelegramChannel] 缺少 bot_token 或 chat_id 配置")
            return False
        text_lines = [f"*{title}*", message]
        if details:
            try:
                text_lines.append(
                    "`" + json.dumps(details, ensure_ascii=False, indent=2) + "`"
                )
            except Exception:
                text_lines.append(f"`{details}`")
        text = "\n".join(text_lines)
        url = self.API_BASE.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return bool(data.get("ok"))
            print(f"[TelegramChannel] 非 200 响应: {resp.status_code} {resp.text[:200]}")
            return False
        except Exception as e:
            print(f"[TelegramChannel] 发送失败: {e}")
            return False


# ---------------------------------------------------------------------------
# 渠道工厂
# ---------------------------------------------------------------------------

CHANNEL_REGISTRY: dict[str, type[NotificationChannel]] = {
    "email": EmailChannel,
    "webhook": WebhookChannel,
    "telegram": TelegramChannel,
}


def build_channel(channel_type: str, channel_config: dict) -> NotificationChannel | None:
    """根据 channel_type 与 channel_config 构建渠道实例。未知类型返回 None。"""
    cls = CHANNEL_REGISTRY.get(channel_type)
    if cls is None:
        return None
    try:
        return cls(channel_config or {})
    except Exception as e:
        print(f"[notification] 构建 {channel_type} 渠道失败: {e}")
        return None


# ---------------------------------------------------------------------------
# NotificationService 单例
# ---------------------------------------------------------------------------

class NotificationService:
    """通知服务单例。

    - init_channels(config): 从系统级配置加载默认渠道（可选）
    - notify(event_type, title, message, details): 查询 DB 中匹配该 event_type 的活跃规则，
      逐个构建渠道实例并发送。每个渠道独立 try/except，互不影响。
    - test_channel(channel_type, channel_config): 测试指定渠道连通性
    """

    _instance: "NotificationService | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # 系统级默认渠道（按 channel_type 索引）
        self._default_channels: dict[str, NotificationChannel] = {}

    # -- 默认渠道（系统级配置，可选）--
    def init_channels(self, config: dict) -> None:
        """根据系统配置初始化默认渠道。

        config 形如：
            {
                "email": {"smtp_host": ..., "to_emails": ...},
                "webhook": {"webhook_url": ...},
                "telegram": {"bot_token": ..., "chat_id": ...}
            }
        """
        self._default_channels.clear()
        for ctype, cfg in (config or {}).items():
            ch = build_channel(ctype, cfg or {})
            if ch is not None:
                self._default_channels[ctype] = ch

    # -- 核心分发 --
    async def notify(
        self,
        event_type: str,
        title: str,
        message: str,
        details: dict | None = None,
    ) -> int:
        """分发通知到所有匹配该 event_type 的活跃规则渠道。

        返回成功发送的渠道数量（0 表示无匹配或全部失败）。
        任何异常都被捕获，绝不向上抛出。
        """
        sent_count = 0
        details = details or {}
        try:
            rules = self._load_rules_for_event(event_type)
        except Exception as e:
            print(f"[notification] 加载规则失败: {e}")
            return 0

        if not rules:
            return 0

        tasks = []
        for rule in rules:
            channel = build_channel(rule["channel_type"], rule["channel_config"])
            if channel is None:
                continue
            tasks.append(self._safe_send(channel, title, message, details))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if r is True:
                sent_count += 1
        return sent_count

    async def _safe_send(
        self, channel: NotificationChannel, title: str, message: str, details: dict
    ) -> bool:
        try:
            return await channel.send(title, message, details)
        except Exception as e:
            print(f"[notification] {channel.channel_type} 发送异常: {e}")
            return False

    def _load_rules_for_event(self, event_type: str) -> list[dict]:
        """查询 DB 中匹配该 event_type 的活跃通知规则。

        延迟导入避免循环依赖。每次调用都查 DB，确保规则变更立即生效。
        """
        from database import SessionLocal
        from models.notification_rule import NotificationRule

        db = SessionLocal()
        try:
            rules = db.query(NotificationRule).filter(
                NotificationRule.is_active == True  # noqa: E712
            ).all()
            matched: list[dict] = []
            for r in rules:
                try:
                    event_types = r.event_types or []
                    if (
                        event_type in event_types
                        or "*" in event_types
                    ):
                        matched.append({
                            "channel_type": r.channel_type,
                            "channel_config": r.channel_config or {},
                        })
                except Exception:
                    continue
            return matched
        finally:
            db.close()

    # -- 测试 --
    async def test_channel(
        self,
        channel_type: str,
        channel_config: dict | None = None,
    ) -> bool:
        """测试指定渠道连通性。

        优先使用传入的 channel_config；未传则使用系统默认渠道。
        """
        if channel_config:
            channel = build_channel(channel_type, channel_config)
        else:
            channel = self._default_channels.get(channel_type)
        if channel is None:
            return False
        try:
            return await channel.send(
                "QuantOKX 通知测试",
                f"这是一条 {channel_type} 渠道的连通性测试消息。",
                {"test": True, "timestamp": int(time.time())},
            )
        except Exception as e:
            print(f"[notification] test_channel {channel_type} 异常: {e}")
            return False


# 单例
notification_service = NotificationService()
