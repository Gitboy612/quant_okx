"""向后兼容模块。

实际实现已迁移至 strategies.hedge_strategy.py，本文件仅做重新导出，
保持 ``from strategies.advanced_grid_hedge_strategy import AdvancedGridHedgeStrategy``
的旧导入路径可用。

注意：该策略实际为对冲策略而非网格策略，详见 hedge_strategy.py 中的类 docstring。
"""
from strategies.hedge_strategy import AdvancedGridHedgeStrategy

__all__ = ["AdvancedGridHedgeStrategy"]
