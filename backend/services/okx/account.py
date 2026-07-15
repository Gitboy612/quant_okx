from .base import OKXBaseClient
from urllib.parse import urlencode


def _build_query(params: dict) -> str:
    filtered = {k: v for k, v in params.items() if v is not None}
    if not filtered:
        return ""
    return "?" + urlencode(filtered)


class AccountAPI:
    def __init__(self, client: OKXBaseClient):
        self._client = client

    async def get_balance(self, ccy: str = None):
        params = {"ccy": ccy}
        path = "/api/v5/account/balance" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        data = resp.get("data", [])
        return data[0] if data else {}

    async def get_positions(self, instType: str = None, instId: str = None):
        params = {"instType": instType, "instId": instId}
        path = "/api/v5/account/positions" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_positions_history(self, instType: str = None, instId: str = None, after: str = None, before: str = None, limit: str = None):
        params = {"instType": instType, "instId": instId, "after": after, "before": before, "limit": limit}
        path = "/api/v5/account/positions-history" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_account_position_risk(self, instType: str = None):
        params = {"instType": instType}
        path = "/api/v5/account/account-position-risk" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_bills(self, instType: str = None, ccy: str = None, mgnMode: str = None, ctType: str = None, after: str = None, before: str = None, limit: str = None):
        params = {"instType": instType, "ccy": ccy, "mgnMode": mgnMode, "ctType": ctType, "after": after, "before": before, "limit": limit}
        path = "/api/v5/account/bills" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_bills_archive(self, instType: str = None, ccy: str = None, mgnMode: str = None, ctType: str = None, after: str = None, before: str = None, limit: str = None):
        params = {"instType": instType, "ccy": ccy, "mgnMode": mgnMode, "ctType": ctType, "after": after, "before": before, "limit": limit}
        path = "/api/v5/account/bills-archive" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_config(self):
        resp = await self._client._request("GET", "/api/v5/account/config", is_private=True)
        return resp.get("data", [])

    async def set_position_mode(self, posMode: str):
        body = {"posMode": posMode}
        resp = await self._client._request("POST", "/api/v5/account/set-position-mode", body=body, is_private=True)
        return resp

    async def set_leverage(self, instId: str, lever: str, mgnMode: str, posSide: str = None):
        body = {"instId": instId, "lever": lever, "mgnMode": mgnMode}
        if posSide is not None:
            body["posSide"] = posSide
        resp = await self._client._request("POST", "/api/v5/account/set-leverage", body=body, is_private=True)
        return resp

    async def get_leverage(self, instId: str, mgnMode: str):
        params = {"instId": instId, "mgnMode": mgnMode}
        path = "/api/v5/account/leverage-info" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_max_size(self, instId: str, tdMode: str, ccy: str = None, px: str = None, leverage: str = None, unSpotOffset: str = None):
        params = {"instId": instId, "tdMode": tdMode, "ccy": ccy, "px": px, "leverage": leverage, "unSpotOffset": unSpotOffset}
        path = "/api/v5/account/max-size" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_max_avail_size(self, instId: str, tdMode: str, ccy: str = None, reduceOnly: bool = None, unSpotOffset: str = None):
        params = {"instId": instId, "tdMode": tdMode, "ccy": ccy, "reduceOnly": reduceOnly, "unSpotOffset": unSpotOffset}
        path = "/api/v5/account/max-avail-size" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def adjust_margin(self, instId: str, posSide: str, type: str, amt: str):
        body = {"instId": instId, "posSide": posSide, "type": type, "amt": amt}
        resp = await self._client._request("POST", "/api/v5/account/position/margin-balance", body=body, is_private=True)
        return resp

    async def get_margin_balance(self, instId: str = None):
        params = {"instId": instId}
        path = "/api/v5/account/margin/balance" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_fee_rates(self, instType: str, instId: str = None, uly: str = None, category: str = None):
        params = {"instType": instType, "instId": instId, "uly": uly, "category": category}
        path = "/api/v5/account/trade-fee" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_position_risk(self, inst_id: str) -> dict | None:
        """查询持仓风险信息（保证金占用率与强平价）。

        通过 GET /api/v5/account/positions 按 instId 过滤，提取保证金、强平价、
        持仓量与方向。保证金占用率无直接字段，用 margin / (|pos| × markPx) 估算；
        若 markPx 缺失或 pos 为 0 导致无法估算，margin_ratio 回退为 margin 原值（float）。

        Args:
            inst_id: 合约ID 如 ETH-USDT-SWAP
        Returns:
            {"margin_ratio": float, "liq_px": float, "margin": str, "pos": str, "pos_side": str}
            无持仓返回 None
        """
        params = {"instType": None, "instId": inst_id}
        path = "/api/v5/account/positions" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        data = resp.get("data", [])
        if not data:
            return None
        pos_info = data[0]
        pos = pos_info.get("pos", "0")
        margin = pos_info.get("margin", "0")
        liq_px = pos_info.get("liqPx", "")
        mark_px = pos_info.get("markPx", "")
        pos_side = pos_info.get("posSide", "")
        # 估算保证金占用率：margin / (|pos| × markPx)
        try:
            pos_f = abs(float(pos))
            margin_f = float(margin) if margin else 0.0
            mark_f = float(mark_px) if mark_px else 0.0
            if pos_f > 0 and mark_f > 0:
                margin_ratio = margin_f / (pos_f * mark_f)
            else:
                margin_ratio = margin_f
        except (ValueError, TypeError):
            margin_ratio = 0.0
        try:
            liq_px_f = float(liq_px) if liq_px else None
        except (ValueError, TypeError):
            liq_px_f = None
        return {
            "margin_ratio": margin_ratio,
            "liq_px": liq_px_f,
            "margin": margin,
            "pos": pos,
            "pos_side": pos_side,
        }
