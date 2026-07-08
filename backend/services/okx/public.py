from .base import OKXBaseClient
from urllib.parse import urlencode


def _build_query(params: dict) -> str:
    filtered = {k: v for k, v in params.items() if v is not None}
    if not filtered:
        return ""
    return "?" + urlencode(filtered)


class PublicAPI:
    def __init__(self, client: OKXBaseClient):
        self._client = client

    async def get_server_time(self):
        resp = await self._client._request("GET", "/api/v5/public/time", is_private=False)
        return resp.get("data", [])

    async def get_instruments(self, instType: str, uly: str = None, instId: str = None):
        params = {"instType": instType, "uly": uly, "instId": instId}
        path = "/api/v5/public/instruments" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_delivery_exercise_history(self, instType: str, uly: str = None, after: str = None, before: str = None, limit: str = None):
        params = {"instType": instType, "uly": uly, "after": after, "before": before, "limit": limit}
        path = "/api/v5/public/delivery-exercise-history" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_open_interest(self, instType: str, uly: str = None, instId: str = None):
        params = {"instType": instType, "uly": uly, "instId": instId}
        path = "/api/v5/public/open-interest" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_funding_rate(self, instId: str):
        params = {"instId": instId}
        path = "/api/v5/public/funding-rate" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_funding_rate_history(self, instId: str, after: str = None, before: str = None, limit: str = None):
        params = {"instId": instId, "after": after, "before": before, "limit": limit}
        path = "/api/v5/public/funding-rate-history" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_mark_price(self, instType: str, uly: str = None, instId: str = None):
        params = {"instType": instType, "uly": uly, "instId": instId}
        path = "/api/v5/public/mark-price" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=False)
        return resp.get("data", [])

    async def get_interest_rate_loan_quota(self):
        resp = await self._client._request("GET", "/api/v5/public/interest-rate-loan-quota", is_private=False)
        return resp.get("data", [])

    async def get_system_status(self):
        resp = await self._client._request("GET", "/api/v5/system/status", is_private=False)
        return resp.get("data", [])
