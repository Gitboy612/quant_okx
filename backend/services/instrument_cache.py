from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from services.okx_client import OKXClient


class InstrumentCache:
    """Instrument 元数据缓存服务（单例）。

    按 instId 缓存合约/现货的元数据 {ctVal, ctType, settleCcy, tickSz, lotSz, minSz}，
    避免在策略运行中重复调用 OKX public/instruments 接口。
    """

    _instance: Optional["InstrumentCache"] = None

    def __new__(cls) -> "InstrumentCache":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._cache: dict[str, dict] = {}
            cls._instance = instance
        return cls._instance

    @staticmethod
    def _infer_inst_type(inst_id: str) -> str:
        """根据 instId 后缀推断 instType。

        - 以 `-SWAP` 结尾 → "SWAP"
        - 以 `-USDT` / `-USD` 结尾且不含 `-SWAP` → "SPOT"
        - 其余默认 "SPOT"
        """
        if inst_id.endswith("-SWAP"):
            return "SWAP"
        if inst_id.endswith("-USDT") or inst_id.endswith("-USD"):
            return "SPOT"
        return "SPOT"

    @staticmethod
    def _fallback() -> dict:
        """网络异常或返回空时的兜底值。"""
        return {
            "ctVal": 1.0,
            "ctType": None,
            "settleCcy": None,
            "tickSz": None,
            "lotSz": None,
            "minSz": None,
        }

    async def get_instrument(self, instId: str, client: Optional[OKXClient] = None) -> dict:
        """获取 instrument 元数据。

        - 缓存命中直接返回
        - 未命中且提供 client 时，调用 OKX API 获取并写入缓存
        - 网络异常或返回空时返回兜底值（不抛异常）
        """
        cached = self._cache.get(instId)
        if cached is not None:
            return cached

        fallback = self._fallback()

        if client is None:
            print(f"[InstrumentCache][WARN] cache miss and no client for {instId}, returning fallback")
            return fallback

        inst_type = self._infer_inst_type(instId)
        try:
            data = await client.public.get_instruments(instType=inst_type, instId=instId)
        except Exception as e:
            print(f"[InstrumentCache][WARN] get_instruments failed for {instId} (instType={inst_type}): {e}")
            return fallback

        if not data:
            print(f"[InstrumentCache][WARN] empty instruments data for {instId} (instType={inst_type}), returning fallback")
            return fallback

        item = data[0]

        ct_val_raw = item.get("ctVal")
        try:
            ct_val = float(ct_val_raw) if ct_val_raw else 1.0
        except (ValueError, TypeError):
            ct_val = 1.0

        entry = {
            "ctVal": ct_val,
            "ctType": item.get("ctType") or None,
            "settleCcy": item.get("settleCcy") or None,
            "tickSz": item.get("tickSz") or None,
            "lotSz": item.get("lotSz") or None,
            "minSz": item.get("minSz") or None,
        }
        self._cache[instId] = entry
        return entry

    def get_ct_val(self, instId: str) -> float:
        """仅查缓存获取 ctVal，未命中返回 1.0（不触发 API 调用，避免在同步上下文中 await）。"""
        entry = self._cache.get(instId)
        if entry is None:
            return 1.0
        ct_val = entry.get("ctVal")
        if ct_val is None:
            return 1.0
        return ct_val

    def clear_cache(self) -> None:
        """清空缓存（测试用）。"""
        self._cache.clear()


instrument_cache = InstrumentCache()
