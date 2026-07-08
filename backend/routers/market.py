import asyncio
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Query

from config import OKX_BASE_URL, OKX_DNS_OVERRIDE

router = APIRouter(tags=["market"])

_cache: Optional[dict] = None
_cache_ts: float = 0
_cache_lock = asyncio.Lock()
_CACHE_TTL = 15.0

_HTTP_CLIENT: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        dns_map: dict[str, str] = {}
        if OKX_DNS_OVERRIDE:
            for pair in OKX_DNS_OVERRIDE.split(","):
                pair = pair.strip()
                if ":" in pair:
                    host, ip = pair.split(":", 1)
                    dns_map[host.strip()] = ip.strip()

        transport = None
        if dns_map:
            dns_map_ref = dns_map

            class DNSOverrideTransport(httpx.AsyncHTTPTransport):
                async def handle_async_request(self, request):
                    from urllib.parse import urlparse
                    parsed = urlparse(str(request.url))
                    host = parsed.hostname or ""
                    if host in dns_map_ref:
                        request.url = request.url.copy_with(host=dns_map_ref[host])
                        request.headers["Host"] = host
                    return await super().handle_async_request(request)

            transport = DNSOverrideTransport()

        _HTTP_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=8.0, read=10.0, write=5.0, pool=3.0),
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
            follow_redirects=True,
            transport=transport,
        )
    return _HTTP_CLIENT


async def _fetch_tickers_from_okx() -> dict:
    client = _get_http_client()
    url = f"{OKX_BASE_URL}/api/v5/market/tickers?instType=SPOT"
    try:
        resp = await client.get(url)
        data = resp.json()
        if data.get("code") != "0":
            return {}
        result = {}
        for item in data.get("data", []):
            inst_id = item.get("instId", "")
            if inst_id.endswith("-USDT"):
                symbol = inst_id.replace("-USDT", "")
                result[symbol] = {
                    "symbol": symbol,
                    "instId": inst_id,
                    "last": item.get("last", "0"),
                    "open24h": item.get("open24h", "0"),
                    "high24h": item.get("high24h", "0"),
                    "low24h": item.get("low24h", "0"),
                    "vol24h": item.get("vol24h", "0"),
                    "volCcy24h": item.get("volCcy24h", "0"),
                    "change24h": _calc_change_pct(item.get("last", "0"), item.get("open24h", "0")),
                    "ts": item.get("ts", "0"),
                }
        return result
    except Exception:
        return {}


def _calc_change_pct(last: str, open24h: str) -> str:
    try:
        l = float(last)
        o = float(open24h)
        if o == 0:
            return "0.00%"
        pct = (l - o) / o * 100
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.2f}%"
    except Exception:
        return "0.00%"


@router.get("/api/market/spot-tickers")
async def get_spot_tickers(symbols: str = Query("BTC,ETH,AVAX,LINK,SOL,HYPE,OKB,BNB,DOGE,XRP,ADA,TRX", description="Comma-separated symbols")):
    global _cache, _cache_ts

    now = time.monotonic()
    if _cache is not None and (now - _cache_ts) < _CACHE_TTL:
        pass
    else:
        async with _cache_lock:
            if _cache is None or (time.monotonic() - _cache_ts) >= _CACHE_TTL:
                fresh = await _fetch_tickers_from_okx()
                if fresh:
                    _cache = fresh
                    _cache_ts = time.monotonic()

    requested = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else []
    if not _cache:
        return {"code": "-1", "msg": "Failed to fetch tickers", "data": {}}

    result = {}
    for sym in requested:
        if sym in _cache:
            result[sym] = _cache[sym]
    return {"code": "0", "data": result}
