from .base import OKXBaseClient
from urllib.parse import urlencode


def _build_query(params: dict) -> str:
    filtered = {k: v for k, v in params.items() if v is not None}
    if not filtered:
        return ""
    return "?" + urlencode(filtered)


def _build_body(params: dict) -> dict:
    return {k: v for k, v in params.items() if v is not None}


class FundingAPI:
    def __init__(self, client: OKXBaseClient):
        self._client = client

    async def get_currencies(self, ccy: str = None):
        params = {"ccy": ccy}
        path = "/api/v5/asset/currencies" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_balances(self, ccy: str = None):
        params = {"ccy": ccy}
        path = "/api/v5/asset/balances" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_bills(self, ccy: str = None, type: str = None, after: str = None, before: str = None, limit: str = None):
        params = {"ccy": ccy, "type": type, "after": after, "before": before, "limit": limit}
        path = "/api/v5/asset/bills" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def transfer(self, ccy: str, amt: str, from_: str, to: str, type: str = '0', subAcct: str = None, fromInstId: str = None, toInstId: str = None, loanTrans: bool = None, clientId: str = None, omitPosRisk: bool = None):
        body = _build_body({
            "ccy": ccy,
            "amt": amt,
            "from": from_,
            "to": to,
            "type": type,
            "subAcct": subAcct,
            "fromInstId": fromInstId,
            "toInstId": toInstId,
            "loanTrans": loanTrans,
            "clientId": clientId,
            "omitPosRisk": omitPosRisk,
        })
        resp = await self._client._request("POST", "/api/v5/asset/transfer", body=body, is_private=True)
        return resp

    async def get_transfer_state(self, transId: str = None, clientId: str = None, type: str = None):
        params = {"transId": transId, "clientId": clientId, "type": type}
        path = "/api/v5/asset/transfer-state" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_deposit_address(self, ccy: str):
        params = {"ccy": ccy}
        path = "/api/v5/asset/deposit-address" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_deposit_history(self, ccy: str = None, txId: str = None, type: str = None, after: str = None, before: str = None, limit: str = None):
        params = {"ccy": ccy, "txId": txId, "type": type, "after": after, "before": before, "limit": limit}
        path = "/api/v5/asset/deposit-history" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_non_tradable_assets(self, ccy: str = None):
        params = {"ccy": ccy}
        path = "/api/v5/asset/non-tradable-assets" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])
