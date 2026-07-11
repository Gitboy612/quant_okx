import asyncio
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from config import OKX_BASE_URL, OKX_DNS_OVERRIDE
from database import get_db
from middleware.auth import get_current_user
from models.account import Account
from models.user import User
from services.instrument_cache import instrument_cache
from services.okx_client import OKXClient

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


def _build_public_client(db: Session) -> Optional[OKXClient]:
    """从第一个可用账户构造 OKXClient（仅需 public 接口，但复用账户凭证）。

    无可用账户时返回 None，调用方应使用兜底值。
    """
    account = db.query(Account).filter(Account.is_active == True).first()  # noqa: E712
    if account is None:
        return None
    return OKXClient(
        api_key_encrypted=account.api_key_encrypted,
        secret_encrypted=account.secret_key_encrypted,
        passphrase_encrypted=account.passphrase_encrypted,
        trade_mode=account.trade_mode,
        account_name=account.name,
    )


@router.get("/api/market/instrument")
async def get_instrument_info(
    instId: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取合约/现货 instrument 元数据（ctVal, tickSz 等）。

    优先从 InstrumentCache 读取；缓存未命中时用第一个可用账户的 OKXClient 拉取并写入缓存。
    无可用账户时返回兜底值 {ctVal: 1.0}。
    """
    client = _build_public_client(db)
    try:
        info = await instrument_cache.get_instrument(instId, client)
    finally:
        if client is not None:
            try:
                client._client.close()
            except Exception:
                pass
            try:
                await client._async_client.aclose()
            except Exception:
                pass
    return {"instId": instId, **info}


@router.get("/api/market/ticker")
async def get_ticker_price(
    symbol: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取某个 instId 的最新成交价（用于稳定币单位换算）。

    使用公共 httpx 客户端直接请求 OKX market/ticker，无需账户凭证。
    """
    http_client = _get_http_client()
    url = f"{OKX_BASE_URL}/api/v5/market/ticker?instId={symbol}"
    try:
        resp = await http_client.get(url)
        data = resp.json()
        if data.get("code") != "0" or not data.get("data"):
            return {"code": "-1", "msg": data.get("msg", "Failed to fetch ticker"), "data": None}
        item = data["data"][0]
        return {
            "code": "0",
            "data": {
                "instId": item.get("instId", symbol),
                "last": item.get("last", "0"),
            },
        }
    except Exception as e:
        return {"code": "-1", "msg": str(e), "data": None}
