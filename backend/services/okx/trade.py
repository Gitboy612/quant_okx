from .base import OKXBaseClient
from .exceptions import OKXAPIException
from urllib.parse import urlencode


def _build_query(params: dict) -> str:
    filtered = {k: v for k, v in params.items() if v is not None}
    if not filtered:
        return ""
    return "?" + urlencode(filtered)


def _build_body(params: dict) -> dict:
    return {k: v for k, v in params.items() if v is not None}


class TradeAPI:
    def __init__(self, client: OKXBaseClient):
        self._client = client

    async def place_order(self, instId: str, tdMode: str, side: str, ordType: str, sz: str, px: str = None, ccy: str = None, posSide: str = None, reduceOnly: bool = None, clOrdId: str = None, tag: str = None, tgtCcy: str = None, banAmend: bool = None):
        body = _build_body({
            "instId": instId,
            "tdMode": tdMode,
            "side": side,
            "ordType": ordType,
            "sz": sz,
            "px": px,
            "ccy": ccy,
            "posSide": posSide,
            "reduceOnly": reduceOnly,
            "clOrdId": clOrdId,
            "tag": tag,
            "tgtCcy": tgtCcy,
            "banAmend": banAmend,
        })
        resp = await self._client._request("POST", "/api/v5/trade/order", body=body, is_private=True)
        return resp

    async def batch_place_orders(self, orders: list):
        resp = await self._client._request("POST", "/api/v5/trade/batch-orders", body=orders, is_private=True)
        return resp

    async def cancel_order(self, instId: str, ordId: str = None, clOrdId: str = None):
        body = _build_body({"instId": instId, "ordId": ordId, "clOrdId": clOrdId})
        resp = await self._client._request("POST", "/api/v5/trade/cancel-order", body=body, is_private=True)
        return resp

    async def batch_cancel_orders(self, orders: list):
        resp = await self._client._request("POST", "/api/v5/trade/cancel-batch-orders", body=orders, is_private=True)
        return resp

    async def amend_order(self, instId: str, ordId: str = None, clOrdId: str = None, newPx: str = None, newSz: str = None, cxlOnFail: bool = None, reqId: str = None):
        body = _build_body({
            "instId": instId,
            "ordId": ordId,
            "clOrdId": clOrdId,
            "newPx": newPx,
            "newSz": newSz,
            "cxlOnFail": cxlOnFail,
            "reqId": reqId,
        })
        resp = await self._client._request("POST", "/api/v5/trade/amend-order", body=body, is_private=True)
        return resp

    async def batch_amend_orders(self, orders: list):
        resp = await self._client._request("POST", "/api/v5/trade/amend-batch-orders", body=orders, is_private=True)
        return resp

    async def close_positions(self, instId: str, mgnMode: str, posSide: str = None, ccy: str = None, autoCxl: bool = None):
        body = _build_body({
            "instId": instId,
            "mgnMode": mgnMode,
            "posSide": posSide,
            "ccy": ccy,
            "autoCxl": autoCxl,
        })
        resp = await self._client._request("POST", "/api/v5/trade/close-position", body=body, is_private=True)
        return resp

    async def get_order(self, instId: str, ordId: str = None, clOrdId: str = None):
        params = {"instId": instId, "ordId": ordId, "clOrdId": clOrdId}
        path = "/api/v5/trade/order" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_pending_orders(self, instType: str = None, instId: str = None, after: str = None, before: str = None, limit: str = None):
        params = {"instType": instType, "instId": instId, "after": after, "before": before, "limit": limit}
        path = "/api/v5/trade/orders-pending" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_orders_history(self, instType: str = None, instId: str = None, after: str = None, before: str = None, limit: str = None):
        params = {"instType": instType, "instId": instId, "after": after, "before": before, "limit": limit}
        path = "/api/v5/trade/orders-history" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_orders_history_archive(self, instType: str = None, instId: str = None, after: str = None, before: str = None, limit: str = None):
        params = {"instType": instType, "instId": instId, "after": after, "before": before, "limit": limit}
        path = "/api/v5/trade/orders-history-archive" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_fills(self, instType: str = None, instId: str = None, after: str = None, before: str = None, limit: str = None):
        params = {"instType": instType, "instId": instId, "after": after, "before": before, "limit": limit}
        path = "/api/v5/trade/fills" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_fills_history(self, instType: str, instId: str = None, after: str = None, before: str = None, limit: str = None):
        params = {"instType": instType, "instId": instId, "after": after, "before": before, "limit": limit}
        path = "/api/v5/trade/fills-history" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def get_order_algos_list(self, algoId: str = None, algoClOrdId: str = None, instType: str = None, after: str = None, before: str = None, limit: str = None, ordType: str = None, clOrdId: str = None, state: str = None):
        params = {
            "algoId": algoId,
            "algoClOrdId": algoClOrdId,
            "instType": instType,
            "after": after,
            "before": before,
            "limit": limit,
            "ordType": ordType,
            "clOrdId": clOrdId,
            "state": state,
        }
        path = "/api/v5/trade/orders-algo-pending" + _build_query(params)
        resp = await self._client._request("GET", path, is_private=True)
        return resp.get("data", [])

    async def cancel_algos(self, orders: list):
        resp = await self._client._request("POST", "/api/v5/trade/cancel-algos", body=orders, is_private=True)
        return resp

    async def set_leverage(self, inst_id: str, lever: int, mgn_mode: str = "cross", pos_side: str | None = None) -> dict:
        """设置合约杠杆倍数与持仓模式。

        Args:
            inst_id: 合约ID 如 ETH-USDT-SWAP
            lever: 杠杆倍数 1-125
            mgn_mode: cross(全仓) / isolated(逐仓)
            pos_side: 单向持仓可不传；双向持仓 long/short
        Returns:
            OKX 响应 dict
        Raises:
            OKXAPIException: 当 OKX 返回 code != 0 时抛出，msg 含错误码映射后的可读描述
        """
        body = _build_body({
            "instId": inst_id,
            "lever": str(lever),
            "mgnMode": mgn_mode,
            "posSide": pos_side,
        })
        resp = await self._client._request("POST", "/api/v5/account/set-leverage", body=body, is_private=True)
        code = str(resp.get("code", "-1"))
        if code != "0":
            err_desc = resp.get("_error_desc", "")
            msg = resp.get("msg", "")
            detail = f"{msg} | {err_desc}" if err_desc else msg
            raise OKXAPIException(code=code, msg=detail, endpoint="/api/v5/account/set-leverage")
        return resp
