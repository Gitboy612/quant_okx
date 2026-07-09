"""积木库子模块占位。

各子模块将在后续 Task 中实现，并通过 registry 装饰器自动注册到对应注册表：

- indicators.py: 指标类积木（IndicatorRef），如 rsi / ma / macd
- conditions.py: 条件类积木（ConditionRef），如 price_above / position_long
- actions.py: 动作类积木（ActionRef），如 open_position / close_position / notify
- events.py: 事件类积木（EventRef，kind 以 on_ 前缀），如 on_signal / on_price_drop
- base_strategies.py: 基础策略类积木（BaseStrategyRef），如 grid / trend

使用前需在 ComposableStrategy 首次使用前导入一次（如 `import dsl.blocks.indicators`）。
"""
