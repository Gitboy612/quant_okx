from .base import OKXBaseClient
from urllib.parse import urlencode


def _build_query(params: dict) -> str:
    filtered = {k: v for k, v in params.items() if v is not None}
    if not filtered:
        return ""
    return "?" + urlencode(filtered)


class MarketAPI:
    def __init__(self, client: OKXBaseClient):
        self._client = client

    async def get_ticker(self, instId: str):
        params = {"instId": instId}
        path = "/api/v5/market/ticker" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_tickers(self, instType: str, uly: str = None):
        params = {"instType": instType, "uly": uly}
        path = "/api/v5/market/tickers" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_index_ticker(self, quoteCcy: str = None, instId: str = None):
        params = {"quoteCcy": quoteCcy, "instId": instId}
        path = "/api/v5/market/index-tickers" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_orderbook(self, instId: str, sz: str = None):
        params = {"instId": instId, "sz": sz}
        path = "/api/v5/market/books" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_candles(self, instId: str, bar: str = None, after: str = None, before: str = None, limit: str = None):
        if bar is None:
            bar = "1m"
        if limit is None:
            limit = "100"
        params = {"instId": instId, "bar": bar, "after": after, "before": before, "limit": limit}
        path = "/api/v5/market/candles" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_candles_history(self, instId: str, bar: str = None, after: str = None, before: str = None, limit: str = None):
        params = {"instId": instId, "bar": bar, "after": after, "before": before, "limit": limit}
        path = "/api/v5/market/history-candles" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_trades(self, instId: str, limit: str = None):
        params = {"instId": instId, "limit": limit}
        path = "/api/v5/market/trades" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_trades_history(self, instId: str, after: str = None, before: str = None, limit: str = None):
        params = {"instId": instId, "after": after, "before": before, "limit": limit}
        path = "/api/v5/market/trades-history" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_option_trades(self, instId: str = None):
        params = {"instId": instId}
        path = "/api/v5/market/option/trades" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])
