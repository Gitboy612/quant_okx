import asyncio
import base64
import hashlib
import hmac
import json
import os
import socket
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import httpx

from config import OKX_BASE_URL, OKX_DNS_OVERRIDE
from services.okx_error_codes import get_error_message

from .exceptions import OKXAPIException


class RateLimiter:
    def __init__(self, max_calls: int, period_seconds: float):
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._lock = asyncio.Lock()
        self._call_timestamps: List[float] = []

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            self._call_timestamps = [t for t in self._call_timestamps if now - t < self.period_seconds]
            while len(self._call_timestamps) >= self.max_calls:
                wait_time = self._call_timestamps[0] + self.period_seconds - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                now = time.monotonic()
                self._call_timestamps = [t for t in self._call_timestamps if now - t < self.period_seconds]
            self._call_timestamps.append(now)


class OKXBaseClient:
    _time_offset_ms: float = 0.0
    _global_proxy: Optional[str] = None
    _synced: bool = False

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        passphrase: str,
        trade_mode: str = "demo",
        base_url: str = None,
        strategy_instance_id: int = None,
        account_name: str = None,
        proxy: str = None,
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.base_url = base_url or OKX_BASE_URL
        self.trade_mode = trade_mode
        self.strategy_instance_id = strategy_instance_id
        self.account_name = account_name
        self._dns_map = self._build_dns_map()

        effective_proxy = proxy or OKXBaseClient._global_proxy or os.getenv("OKX_PROXY", "") or None

        limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        timeout = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=5.0)

        transport = self._make_async_transport()

        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            proxy=effective_proxy,
            transport=transport,
            limits=limits,
        )

        self._public_limiter = RateLimiter(max_calls=20, period_seconds=2.0)
        self._private_limiter = RateLimiter(max_calls=60, period_seconds=2.0)
        self._client_lock = asyncio.Lock()

    async def _ensure_synced(self):
        if not OKXBaseClient._synced:
            await self._sync_time()
            OKXBaseClient._synced = True

    @classmethod
    def set_global_proxy(cls, proxy_url: Optional[str]):
        cls._global_proxy = proxy_url

    def _build_dns_map(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        if OKX_DNS_OVERRIDE:
            for pair in OKX_DNS_OVERRIDE.split(","):
                pair = pair.strip()
                if ":" in pair:
                    host, ip = pair.split(":", 1)
                    mapping[host.strip()] = ip.strip()
        return mapping

    def _make_async_transport(self):
        if not self._dns_map:
            return None
        dns_map = self._dns_map

        class AsyncDNSOverrideTransport(httpx.AsyncHTTPTransport):
            async def handle_async_request(self, request):
                from urllib.parse import urlparse
                parsed = urlparse(str(request.url))
                host = parsed.hostname or ""
                if host in dns_map:
                    request.url = request.url.copy_with(host=dns_map[host])
                    request.headers["Host"] = host
                return await super().handle_async_request(request)

        return AsyncDNSOverrideTransport()

    def _server_now_ms(self) -> int:
        return int(time.time() * 1000) + int(OKXBaseClient._time_offset_ms)

    def _iso_timestamp(self) -> str:
        ts_s = self._server_now_ms() / 1000.0
        dt = datetime.fromtimestamp(ts_s, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

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

    def _log_call(
        self,
        endpoint: str,
        method: str,
        request_body: str,
        response_body: str,
        response_code: str,
        status: str,
        req_meta: str = "",
    ):
        log_req = f"{req_meta} | body={request_body}" if request_body else req_meta
        try:
            from database import SessionLocal
            from models.api_call_log import ApiCallLog
            db = SessionLocal()
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

    async def _sync_time(self, silent: bool = False) -> bool:
        headers = {}
        if self.trade_mode == "demo":
            headers["x-simulated-trading"] = "1"
        for attempt in range(3):
            try:
                url = self.base_url + "/api/v5/public/time"
                resp = await self._client.get(url, timeout=5.0, headers=headers)
                raw = resp.text.strip()
                if not raw:
                    if not silent:
                        self._log_system("SYNC_TIME_FAIL", f"attempt={attempt+1} status={resp.status_code} body=empty")
                    await asyncio.sleep(1)
                    continue
                data = resp.json()
                if data.get("code") == "0" and data.get("data"):
                    server_ts_ms = float(data["data"][0]["ts"])
                    local_ts_ms = time.time() * 1000
                    OKXBaseClient._time_offset_ms = server_ts_ms - local_ts_ms
                    if not silent:
                        self._log_system(
                            "SYNC_TIME_OK",
                            f"offset={OKXBaseClient._time_offset_ms:.0f}ms server={datetime.fromtimestamp(server_ts_ms/1000, tz=timezone.utc).isoformat()}",
                        )
                    return True
                else:
                    if not silent:
                        self._log_system("SYNC_TIME_FAIL", f"attempt={attempt+1} code={data.get('code')} msg={data.get('msg','')}")
            except Exception as e:
                if not silent:
                    self._log_system("SYNC_TIME_ERR", f"attempt={attempt+1} {e}")
            await asyncio.sleep(1)
        return False

    def _is_retryable_error(self, code: str, status_code: int, exception: Optional[Exception] = None) -> bool:
        if exception is not None:
            return True
        if 500 <= status_code < 600:
            return True
        if code == "50011":
            return True
        return False

    async def _request(
        self,
        method: str,
        path: str,
        body: Union[Dict[str, Any], List[Any], None] = None,
        is_private: bool = True,
    ) -> Dict[str, Any]:
        await self._ensure_synced()

        if is_private:
            await self._private_limiter.acquire()
        else:
            await self._public_limiter.acquire()

        max_retries = 3
        retry_delays = [1, 2, 4]

        body_str = ""
        req_meta = ""
        last_exception = None

        for retry_attempt in range(max_retries + 1):
            resynced = False
            try:
                timestamp = self._iso_timestamp()
                body_str = json.dumps(body) if body else ""
                sign = self._sign(timestamp, method, path, body_str) if is_private else ""

                headers: Dict[str, str] = {
                    "Content-Type": "application/json",
                }
                if is_private:
                    headers["OK-ACCESS-KEY"] = self.api_key
                    headers["OK-ACCESS-SIGN"] = sign
                    headers["OK-ACCESS-TIMESTAMP"] = timestamp
                    headers["OK-ACCESS-PASSPHRASE"] = self.passphrase
                if self.trade_mode == "demo":
                    headers["x-simulated-trading"] = "1"

                req_meta = f"v2 mode={'demo' if self.trade_mode == 'demo' else 'live'} ts={timestamp}"
                if is_private:
                    req_meta += f" sign={sign[:16]}... key={self.api_key[:12]}... pass={self.passphrase[:4]}***"
                req_meta += f" offset_ms={OKXBaseClient._time_offset_ms:.0f}"

                url = self.base_url + path

                resp = await self._client.request(
                    method, url, headers=headers, content=body_str if body_str else None
                )
                raw_text = resp.text.strip()
                if not raw_text:
                    content_type = resp.headers.get("content-type", "unknown")
                    location = resp.headers.get("location", "")
                    resp_json = {
                        "code": "-1",
                        "msg": f"OKX 返回空响应 (HTTP {resp.status_code}, Content-Type: {content_type})" +
                               (f"，重定向到: {location}" if location else "") +
                               f"，接入点 {self.base_url} 的 API 不可用",
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

                    if resp_code in ("50112", "50115") and not resynced:
                        self._log_call(path, method, body_str, resp_str, resp_code, "retry_syncing", req_meta)
                        synced = await self._sync_time(silent=True)
                        if synced:
                            resynced = True
                            continue

                if status != "success" and self._is_retryable_error(resp_code, resp.status_code):
                    if retry_attempt < max_retries:
                        delay = retry_delays[retry_attempt]
                        self._log_call(path, method, body_str, resp_str, resp_code, f"retry_{retry_attempt+1}", req_meta)
                        await asyncio.sleep(delay)
                        continue

                self._log_call(path, method, body_str, resp_str, resp_code, status, req_meta)
                return resp_json

            except (httpx.HTTPError, OSError, socket.error) as e:
                last_exception = e
                err_msg = str(e)
                if isinstance(e, OSError) and "getaddrinfo" in err_msg:
                    err_msg = f"DNS解析失败：无法连接 {self.base_url}，请检查网络或设置环境变量 OKX_BASE_URL 切换接入点"
                if retry_attempt < max_retries:
                    delay = retry_delays[retry_attempt]
                    self._log_system("RETRY", f"attempt={retry_attempt+1} path={method} {path} err={err_msg} delay={delay}s")
                    await asyncio.sleep(delay)
                    continue
                resp_code = "network_error"
                resp_str = err_msg
                resp_json = {"code": "-1", "msg": err_msg}
                status = "network_error"
                self._log_call(path, method, body_str, resp_str, resp_code, status, req_meta)
                return resp_json
            except Exception as e:
                last_exception = e
                resp_code = "exception"
                resp_str = str(e)
                resp_json = {"code": "-1", "msg": str(e)}
                status = "exception"
                self._log_call(path, method, body_str, resp_str, resp_code, status, req_meta)
                return resp_json

        if last_exception:
            resp_json = {"code": "-1", "msg": str(last_exception)}
            return resp_json
        return {"code": "-1", "msg": "Max retries exceeded"}

    async def aclose(self):
        await self._client.aclose()

    async def __aenter__(self):
        await self._ensure_synced()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()
