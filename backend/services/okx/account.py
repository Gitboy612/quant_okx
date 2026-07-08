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
