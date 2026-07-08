import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from models.account import Account
from models.log import OperationLog
from schemas.auth import AccountCreate, AccountUpdate
from services.encryption_service import encrypt, decrypt
from services.okx_client import OKXClient
from middleware.auth import get_current_user
from config import OKX_BASE_URL, OKX_ALT_URLS

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


def _account_to_response(acc: Account) -> dict:
    return {
        "id": acc.id,
        "name": acc.name,
        "trade_mode": acc.trade_mode,
        "exchange": acc.exchange,
        "is_active": acc.is_active,
        "api_key_masked": _mask_key(acc.api_key_encrypted[:16]) if acc.api_key_encrypted else "****",
        "created_at": acc.created_at.isoformat() if acc.created_at else "",
    }


@router.get("")
def list_accounts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    accounts = db.query(Account).all()
    return [_account_to_response(a) for a in accounts]


@router.post("")
def create_account(
    body: AccountCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    test_client = OKXClient(
        api_key_encrypted=encrypt(body.api_key),
        secret_encrypted=encrypt(body.secret_key),
        passphrase_encrypted=encrypt(body.passphrase) if body.passphrase else None,
        trade_mode=body.trade_mode,
        account_name=body.name,
    )
    verify = test_client._request("GET", "/api/v5/account/balance")
    if verify.get("code") != "0":
        raise HTTPException(status_code=400, detail=f"API Key 验证失败: {verify.get('msg', '未知错误')}")

    account = Account(
        name=body.name,
        api_key_encrypted=encrypt(body.api_key),
        secret_key_encrypted=encrypt(body.secret_key),
        passphrase_encrypted=encrypt(body.passphrase) if body.passphrase else None,
        trade_mode=body.trade_mode,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    log = OperationLog(
        user_id=user.id,
        action="add_account",
        target_type="account",
        target_id=account.id,
        detail={"name": body.name, "trade_mode": body.trade_mode, "verify": "ok"},
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return {"message": f"账户「{body.name}」验证成功，已添加", "account": _account_to_response(account)}


@router.put("/{account_id}")
def update_account(
    account_id: int,
    body: AccountUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账户不存在")

    if body.name is not None:
        account.name = body.name
    if body.api_key is not None:
        account.api_key_encrypted = encrypt(body.api_key)
    if body.secret_key is not None:
        account.secret_key_encrypted = encrypt(body.secret_key)
    if body.passphrase is not None:
        account.passphrase_encrypted = encrypt(body.passphrase) if body.passphrase else None
    if body.trade_mode is not None:
        account.trade_mode = body.trade_mode
    if body.is_active is not None:
        account.is_active = body.is_active

    db.commit()
    db.refresh(account)

    log = OperationLog(
        user_id=user.id,
        action="update_account",
        target_type="account",
        target_id=account.id,
        detail={"name": account.name},
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return _account_to_response(account)


@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账户不存在")

    db.delete(account)

    log = OperationLog(
        user_id=user.id,
        action="delete_account",
        target_type="account",
        target_id=account_id,
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    db.commit()

    return {"message": "账户已删除"}


@router.get("/{account_id}/balance")
def get_balance(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账户不存在")

    try:
        client = OKXClient(
            api_key_encrypted=account.api_key_encrypted,
            secret_encrypted=account.secret_key_encrypted,
            passphrase_encrypted=account.passphrase_encrypted,
            trade_mode=account.trade_mode,
            account_name=account.name,
        )
        balances = asyncio.run(client.get_balance())
        assets = []
        total_equity = 0.0
        try:
            total_equity = float(balances.get("totalEq", "0"))
            for det in balances.get("details", []):
                avail = float(det.get("availBal", "0"))
                frozen = float(det.get("frozenBal", "0"))
                ccy = det.get("ccy", "")
                eq = float(det.get("eq", "0"))
                if avail > 0 or frozen > 0 or eq > 0:
                    assets.append({
                        "ccy": ccy,
                        "avail": round(avail, 6),
                        "frozen": round(frozen, 6),
                        "equity": round(eq, 6),
                    })
            assets.sort(key=lambda x: x["equity"], reverse=True)
        except Exception:
            pass

        return {
            "total_equity": round(total_equity, 2),
            "assets": assets,
            "asset_count": len(assets),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取余额失败: {str(e)}")


@router.get("/{account_id}/positions")
def get_positions(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账户不存在")

    try:
        client = OKXClient(
            api_key_encrypted=account.api_key_encrypted,
            secret_encrypted=account.secret_key_encrypted,
            passphrase_encrypted=account.passphrase_encrypted,
            trade_mode=account.trade_mode,
            account_name=account.name,
        )
        resp = client._request("GET", "/api/v5/account/positions")
        data = resp.get("data", [])

        positions = []
        for pos in data:
            if pos.get("pos", "0") == "0":
                continue
            positions.append({
                "instId": pos.get("instId", ""),
                "posSide": pos.get("posSide", ""),
                "pos": pos.get("pos", "0"),
                "markPx": pos.get("markPx", "0"),
                "upl": pos.get("upl", "0"),
                "avgPx": pos.get("avgPx", "0"),
                "notionalUsd": pos.get("notionalUsd", "0"),
            })

        return positions
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取持仓失败: {str(e)}")


@router.get("/{account_id}/balance/cached")
def get_balance_cached(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return cached balance from latest PnlRecord, avoiding OKX API call."""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账户不存在")

    from models.pnl import PnlRecord
    from sqlalchemy import or_
    latest = db.query(PnlRecord).filter(
        or_(PnlRecord.account_id == account_id, PnlRecord.account_id == None)
    ).order_by(PnlRecord.recorded_at.desc()).first()

    if latest:
        return {
            "total_equity": latest.equity or 0,
            "unrealized_pnl": latest.unrealized_pnl or 0,
            "realized_pnl": latest.realized_pnl or 0,
            "cached_at": latest.recorded_at.isoformat() if latest.recorded_at else None,
            "source": "cached",
        }
    return {
        "total_equity": 0,
        "unrealized_pnl": 0,
        "realized_pnl": 0,
        "cached_at": None,
        "source": "cached",
    }


@router.get("/network-check")
def check_network_connectivity(
    user: User = Depends(get_current_user),
):
    import socket

    urls_to_test = [OKX_BASE_URL] + [u for u in OKX_ALT_URLS if u]

    results = []
    for url in urls_to_test:
        host = url.replace("https://", "").replace("http://", "").rstrip("/")
        try:
            socket.getaddrinfo(host, 443)
            results.append({"url": url, "host": host, "dns_ok": True})
        except socket.gaierror:
            results.append({"url": url, "host": host, "dns_ok": False})

    reachable = [r for r in results if r["dns_ok"]]
    unreachable = [r for r in results if not r["dns_ok"]]

    return {
        "current_base_url": OKX_BASE_URL,
        "results": results,
        "reachable_count": len(reachable),
        "tip": (
            "所有接入点均不可达" if not reachable
            else f"当前使用 {OKX_BASE_URL}，可连通" if any(r["url"] == OKX_BASE_URL and r["dns_ok"] for r in results)
            else f"当前 {OKX_BASE_URL} 不可达。请在 .env 中设置 OKX_BASE_URL={next((r['url'] for r in reachable), '')}"
        ),
    }
