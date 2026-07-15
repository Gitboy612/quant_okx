import asyncio
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
import httpx
import os
from database import SessionLocal
from services.encryption_service import decrypt
from services.okx_error_codes import get_error_message
from config import OKX_BASE_URL, OKX_DNS_OVERRIDE

from services.okx.base import OKXBaseClient
from services.okx.public import PublicAPI
from services.okx.market import MarketAPI
from services.okx.account import AccountAPI
from services.okx.trade import TradeAPI
from services.okx.funding import FundingAPI


class OKXClient:
    _time_offset_ms: float = 0.0
    _global_proxy: str | None = None
    _synced: bool = False

    def __init__(self, api_key_encrypted: str, secret_encrypted: str, passphrase_encrypted: str | None,
                 trade_mode: str = "demo", strategy_instance_id: int | None = None, account_name: str | None = None,
                 proxy: str | None = None):
        self.api_key = decrypt(api_key_encrypted)
        self.secret_key = decrypt(secret_encrypted)
        self.passphrase = decrypt(passphrase_encrypted) if passphrase_encrypted else ""
        self.base_url = OKX_BASE_URL
        self.trade_mode = trade_mode
        self.strategy_instance_id = strategy_instance_id
        self.account_name = account_name
        self._dns_map = self._build_dns_map()

        effective_proxy = proxy or OKXClient._global_proxy or os.getenv("OKX_PROXY", "") or None
        self._client = httpx.Client(
            timeout=15,
            follow_redirects=True,
            proxy=effective_proxy,
            transport=self._make_transport(),
        )
        self._time_synced = False

        self._async_client = OKXBaseClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
            passphrase=self.passphrase,
            trade_mode=self.trade_mode,
            base_url=self.base_url,
            strategy_instance_id=strategy_instance_id,
            account_name=account_name,
            proxy=proxy,
        )
        self.public = PublicAPI(self._async_client)
        self.market = MarketAPI(self._async_client)
        self.account = AccountAPI(self._async_client)
        self.trade = TradeAPI(self._async_client)
        self.funding = FundingAPI(self._async_client)

    @classmethod
    def set_global_proxy(cls, proxy_url: str | None):
        cls._global_proxy = proxy_url
        OKXBaseClient.set_global_proxy(proxy_url)

    def _build_dns_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        if OKX_DNS_OVERRIDE:
            for pair in OKX_DNS_OVERRIDE.split(","):
                pair = pair.strip()
                if ":" in pair:
                    host, ip = pair.split(":", 1)
                    mapping[host.strip()] = ip.strip()
        return mapping

    def _make_transport(self):
        if not self._dns_map:
            return None
        dns_map = self._dns_map
        class DNSOverrideTransport(httpx.HTTPTransport):
            def handle_request(self, request):
                from urllib.parse import urlparse
                parsed = urlparse(str(request.url))
                host = parsed.hostname or ""
                if host in dns_map:
                    request.url = request.url.copy_with(host=dns_map[host])
                    request.headers["Host"] = host
                return super().handle_request(request)
        return DNSOverrideTransport()

    def _server_now_ms(self) -> int:
        return int(time.time() * 1000) + int(OKXClient._time_offset_ms)

    def _iso_timestamp(self) -> str:
        ts_s = self._server_now_ms() / 1000.0
        dt = datetime.fromtimestamp(ts_s, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    def _sync_time(self, silent: bool = False) -> bool:
        headers = {}
        if self.trade_mode == "demo":
            headers["x-simulated-trading"] = "1"
        for attempt in range(3):
            try:
                url = self.base_url + "/api/v5/public/time"
                resp = self._client.get(url, timeout=5, headers=headers)
                raw = resp.text.strip()
                if not raw:
                    if not silent:
                        self._log_system("SYNC_TIME_FAIL", f"attempt={attempt+1} status={resp.status_code} body=empty")
                    time.sleep(1)
                    continue
                data = resp.json()
                if data.get("code") == "0" and data.get("data"):
                    server_ts_ms = float(data["data"][0]["ts"])
                    local_ts_ms = time.time() * 1000
                    OKXClient._time_offset_ms = server_ts_ms - local_ts_ms
                    if not silent:
                        self._log_system("SYNC_TIME_OK", f"offset={OKXClient._time_offset_ms:.0f}ms server={datetime.fromtimestamp(server_ts_ms/1000, tz=timezone.utc).isoformat()}")
                    return True
                else:
                    if not silent:
                        self._log_system("SYNC_TIME_FAIL", f"attempt={attempt+1} code={data.get('code')} msg={data.get('msg','')}")
            except Exception as e:
                if not silent:
                    self._log_system("SYNC_TIME_ERR", f"attempt={attempt+1} {e}")
            time.sleep(1)
        return False

    async def _ensure_time_synced(self):
        if not self._time_synced:
            await asyncio.to_thread(self._sync_time)
            self._time_synced = True

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        message = timestamp + method + path + body
        mac = hmac.new(self.secret_key.encode(), message.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _log_system(self, event: str, detail: str):
        try:
            from services.log_service import log_api_call
            log_api_call(
                account_name=self.account_name,
                method="SYSTEM",
                endpoint=event,
                status="info",
                response_code="0",
                request_body=detail,
                response_body="",
            )
        except Exception:
            pass

    def _log_call(self, endpoint: str, method: str, request_body: str, response_body: str,
                  response_code: str, status: str, req_meta: str = ""):
        log_req = f"{req_meta} | body={request_body}" if request_body else req_meta
        try:
            db = SessionLocal()
            from models.api_call_log import ApiCallLog
            log = ApiCallLog(
                strategy_instance_id=self.strategy_instance_id,
                account_name=self.account_name,
                endpoint=endpoint,
                method=method,
                request_body=log_req[:4000] if log_req else None,
                response_code=response_code,
                response_body=response_body[:4000] if response_body else None,
                status=status,
            )
            db.add(log)
            db.commit()
            db.close()
        except Exception:
            pass

        try:
            from services.log_service import log_api_call
            log_api_call(
                account_name=self.account_name,
                method=method,
                endpoint=endpoint,
                status=status,
                response_code=response_code,
                request_body=log_req,
                response_body=response_body,
            )
        except Exception:
            pass

    def _request(self, method: str, path: str, body: dict | None = None, _retry: bool = True) -> dict:
        timestamp = self._iso_timestamp()
        body_str = json.dumps(body) if body else ""
        sign = self._sign(timestamp, method, path, body_str)

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if self.trade_mode == "demo":
            headers["x-simulated-trading"] = "1"

        req_meta = f"v2 mode={'demo' if self.trade_mode == 'demo' else 'live'} ts={timestamp} sign={sign[:16]}... key={self.api_key[:12]}... pass={self.passphrase[:4]}*** offset_ms={OKXClient._time_offset_ms:.0f}"

        url = self.base_url + path
        try:
            resp = self._client.request(method, url, headers=headers, content=body_str if body_str else None)
            # 从响应头更新限流配额状态（同步路径）
            self._async_client._update_rate_limit_from_headers(resp)
            raw_text = resp.text.strip()
            if not raw_text:
                content_type = resp.headers.get("content-type", "unknown")
                location = resp.headers.get("location", "")
                resp_json = {
                    "code": "-1",
                    "msg": f"OKX 返回空响应 (HTTP {resp.status_code}, Content-Type: {content_type})" +
                           (f"，重定向到: {location}" if location else "") +
                           f"，接入点 {self.base_url} 的 API 不可用"
                }
                resp_code = "empty_response"
                resp_str = json.dumps(resp_json, ensure_ascii=False)
                status = "empty_response"
            else:
                resp_json = resp.json()
                resp_code = str(resp_json.get("code", resp.status_code))
                resp_str = json.dumps(resp_json, ensure_ascii=False)
                status = "success" if resp_json.get("code") == "0" else "error"

                if status == "error":
                    err_msg = get_error_message(resp_code)
                    resp_json["_error_desc"] = err_msg
                    resp_str = json.dumps(resp_json, ensure_ascii=False)

                if resp_code in ("50112", "50115") and _retry:
                    self._log_call(path, method, body_str, resp_str, resp_code, "retry_syncing", req_meta)
                    synced = self._sync_time(silent=True)
                    if synced:
                        return self._request(method, path, body, _retry=False)

        except OSError as e:
            err_msg = str(e)
            if "getaddrinfo" in err_msg:
                err_msg = f"DNS解析失败：无法连接 {self.base_url}，请检查网络或设置环境变量 OKX_BASE_URL 切换接入点"
            resp_code = "network_error"
            resp_str = err_msg
            resp_json = {"code": "-1", "msg": err_msg}
            status = "network_error"
        except Exception as e:
            resp_code = "exception"
            resp_str = str(e)
            resp_json = {"code": "-1", "msg": str(e)}
            status = "exception"

        self._log_call(path, method, body_str, resp_str, resp_code, status, req_meta)
        return resp_json

    async def aclose(self):
        await self._async_client.aclose()
        self._client.close()

    def get_rate_limit_status(self) -> dict:
        """返回当前 API 限流配额状态。

        从最近一次请求的响应头中读取 X-RateLimit-Remaining / X-RateLimit-Limit。
        在尚未发起任何请求时返回 None 值。

        Returns:
            {"remaining": int|None, "limit": int|None, "percentage": float|None}
            percentage = remaining / limit * 100，limit 为 0 或 None 时为 None。
        """
        remaining = self._async_client._rate_limit_remaining
        limit = self._async_client._rate_limit_limit
        percentage = None
        if limit and limit > 0 and remaining is not None:
            percentage = round(remaining / limit * 100, 1)
        return {
            "remaining": remaining,
            "limit": limit,
            "percentage": percentage,
        }

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            pass

    async def get_balance(self) -> dict:
        await self._ensure_time_synced()
        return await self.account.get_balance(ccy=None)

    async def get_positions(self) -> list:
        return await self.account.get_positions()

    async def get_ticker(self, inst_id: str) -> list:
        await self._ensure_time_synced()
        return await self.market.get_ticker(instId=inst_id)

    async def get_candles(self, inst_id: str, bar: str = "1m", limit: str = "100") -> list:
        await self._ensure_time_synced()
        return await self.market.get_candles(instId=inst_id, bar=bar, limit=limit)

    async def place_order(self, inst_id: str, side: str, ord_type: str, sz: str, px: str | None = None) -> dict:
        await self._ensure_time_synced()
        # post_only 同 limit 一样需要 px（Task 9: maker-only 下单）
        body_px = px if (px and ord_type in ("limit", "post_only")) else None
        return await self.trade.place_order(
            instId=inst_id,
            tdMode="cross",
            side=side,
            ordType=ord_type,
            sz=sz,
            px=body_px,
        )

    async def batch_place_orders(self, orders: list[dict]) -> dict:
        await self._ensure_time_synced()
        processed_orders = []
        for o in orders:
            item = {
                "instId": o["instId"],
                "side": o["side"],
                "ordType": o.get("ordType", "limit"),
                "sz": o["sz"],
                "tdMode": "cross",
            }
            if "px" in o:
                item["px"] = o["px"]
            processed_orders.append(item)
        return await self.trade.batch_place_orders(orders=processed_orders)

    async def cancel_order(self, inst_id: str, order_id: str) -> dict:
        await self._ensure_time_synced()
        return await self.trade.cancel_order(instId=inst_id, ordId=order_id)

    async def get_order(self, inst_id: str, order_id: str) -> list:
        await self._ensure_time_synced()
        return await self.trade.get_order(instId=inst_id, ordId=order_id)

    async def get_pending_orders(self, inst_id: str | None = None) -> list:
        await self._ensure_time_synced()
        return await self.trade.get_pending_orders(instId=inst_id)

    async def get_orders_history(self, inst_id: str, limit: str = "50") -> list:
        await self._ensure_time_synced()
        return await self.trade.get_orders_history(instId=inst_id, limit=limit)

    async def set_leverage(self, inst_id: str, lever: int, mgn_mode: str = "cross", pos_side: str | None = None) -> dict:
        """转发至 TradeAPI.set_leverage，设置合约杠杆（SubTask 2.2）。"""
        await self._ensure_time_synced()
        return await self.trade.set_leverage(
            inst_id=inst_id, lever=lever, mgn_mode=mgn_mode, pos_side=pos_side,
        )

    async def get_position_risk(self, inst_id: str) -> dict | None:
        """转发至 AccountAPI.get_position_risk，查询保证金占用率与强平价（SubTask 3.2）。"""
        await self._ensure_time_synced()
        return await self.account.get_position_risk(inst_id=inst_id)
