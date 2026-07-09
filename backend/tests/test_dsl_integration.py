"""数据模型与 Engine 集成测试（Task 12）。

验证可拼接策略 DSL 已正确集成到 quant_okx 的数据模型与策略引擎：

- StrategyTemplate 模型新增 dsl_config 列
- StrategyTemplateCreate schema 新增 dsl_config 可选字段
- strategy_engine._strategy_map 注册了 "composable" -> ComposableStrategy
- ComposableStrategy 可从 dsl.executor 正常导入

测试不连接数据库：列定义用类属性检查，schema 用 Pydantic 实例化，
_strategy_map 用字典查找。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import Column

from models.strategy import StrategyTemplate
from schemas.strategy import StrategyTemplateCreate
from dsl.executor import ComposableStrategy
from services.strategy_engine import StrategyEngine


def test_strategy_template_has_dsl_config_column():
    """StrategyTemplate 类应有 dsl_config 属性，且为 SQLAlchemy Column。"""
    assert hasattr(StrategyTemplate, "dsl_config"), "StrategyTemplate 缺少 dsl_config 属性"
    # 声明式映射中类层访问返回 InstrumentedAttribute，通过 __table__ 取真实 Column
    assert "dsl_config" in StrategyTemplate.__table__.columns, "dsl_config 未在表列定义中"
    col = StrategyTemplate.__table__.columns["dsl_config"]
    assert isinstance(col, Column), f"dsl_config 不是 Column，而是 {type(col)}"
    # nullable 应为 True（向后兼容）
    assert col.nullable is True, "dsl_config 应为 nullable=True"


def test_schema_create_accepts_dsl_config():
    """StrategyTemplateCreate 接受 dsl_config 字段。"""
    dsl_config = {
        "version": "1.0",
        "base_strategy": {"kind": "grid", "params": {"symbol": "BTC-USDT"}},
        "rules": [],
    }
    schema = StrategyTemplateCreate(
        name="可拼接网格",
        strategy_type="composable",
        default_params={"symbol": "BTC-USDT"},
        dsl_config=dsl_config,
    )
    assert schema.dsl_config == dsl_config
    assert schema.dsl_config["version"] == "1.0"
    assert schema.dsl_config["base_strategy"]["kind"] == "grid"


def test_schema_create_dsl_config_optional():
    """不传 dsl_config 也能创建 StrategyTemplateCreate（默认 None）。"""
    schema = StrategyTemplateCreate(
        name="传统网格",
        strategy_type="grid",
        default_params={"upper_price": 50000, "lower_price": 40000},
    )
    assert schema.dsl_config is None


def test_strategy_map_has_composable():
    """strategy_engine._strategy_map 应包含 'composable' 键，值为 ComposableStrategy 类。"""
    strategy_map = StrategyEngine._strategy_map
    assert "composable" in strategy_map, "_strategy_map 缺少 'composable' 键"
    assert strategy_map["composable"] is ComposableStrategy, (
        "'composable' 注册值不是 ComposableStrategy 类"
    )
    # 确保未破坏现有四种硬编码策略
    for key in ("grid", "trend", "arbitrage", "advanced_grid_hedge"):
        assert key in strategy_map, f"现有策略 {key} 注册丢失"


def test_composable_strategy_importable():
    """能从 dsl.executor 导入 ComposableStrategy，且为类对象。"""
    from dsl.executor import ComposableStrategy as Imported

    assert Imported is ComposableStrategy
    import inspect

    assert inspect.isclass(Imported), "ComposableStrategy 应为类"
    assert Imported.__name__ == "ComposableStrategy"
