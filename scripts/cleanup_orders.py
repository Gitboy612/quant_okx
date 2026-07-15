"""清理策略 #1 遗留的挂单（直接调 OKX API）。"""
import sys
import asyncio
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
for _p in (str(_PROJECT_ROOT), str(_BACKEND_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from database import SessionLocal
from models.account import Account
from services.okx_client import OKXClient


async def main():
    db = SessionLocal()
    try:
        acct = db.query(Account).filter(Account.id == 1).first()
        client = OKXClient(
            api_key_encrypted=acct.api_key_encrypted,
            secret_encrypted=acct.secret_key_encrypted,
            passphrase_encrypted=acct.passphrase_encrypted,
            trade_mode=acct.trade_mode,
        )
        try:
            # 查询所有 ETH-USDT-SWAP 挂单
            pending = await client.get_pending_orders("ETH-USDT-SWAP")
            print(f"Pending orders count: {len(pending) if pending else 0}")
            if pending:
                for o in pending[:5]:
                    print(f"  Sample: {o}")
                # 逐个撤销
                cancelled = 0
                for o in pending:
                    ord_id = o.get("ordId")
                    if ord_id:
                        try:
                            resp = await client.cancel_order("ETH-USDT-SWAP", ord_id)
                            if resp.get("code") == "0":
                                cancelled += 1
                            else:
                                print(f"  Cancel {ord_id} failed: {resp}")
                        except Exception as e:
                            print(f"  Cancel {ord_id} exception: {e}")
                print(f"Cancelled {cancelled}/{len(pending)} orders")
        finally:
            try:
                await client.close()
            except Exception:
                pass
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
