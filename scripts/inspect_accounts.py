"""快速调研：用户表 + 当前持仓 + 当前 ETH 价格。"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
for _p in (str(_PROJECT_ROOT), str(_BACKEND_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import asyncio
from database import SessionLocal
from models.user import User
from models.account import Account
from services import encryption_service as encryption_svc
from services.okx_client import OKXClient


async def main():
    db = SessionLocal()
    try:
        print("=== Users ===")
        users = db.query(User).all()
        for u in users:
            print(f"  id={u.id} username={u.username} email={getattr(u, 'email', None)}")

        print("\n=== Accounts (decrypted) ===")
        accts = db.query(Account).all()
        for a in accts:
            try:
                ak = encryption_svc.decrypt(a.api_key_encrypted)
                sk = encryption_svc.decrypt(a.secret_key_encrypted)
                pp = encryption_svc.decrypt(a.passphrase_encrypted) if a.passphrase_encrypted else ""
                print(f"  id={a.id} name={a.name} mode={a.trade_mode}")
                print(f"    api_key={ak[:6]}...{ak[-4:]}")
                print(f"    secret={sk[:4]}...")
                print(f"    passphrase={'set' if pp else 'empty'}")

                # Try to fetch balance & position
                client = OKXClient(
                    api_key_encrypted=a.api_key_encrypted,
                    secret_encrypted=a.secret_key_encrypted,
                    passphrase_encrypted=a.passphrase_encrypted,
                    trade_mode=a.trade_mode,
                )
                try:
                    balance = await client.get_balance()
                    print(f"    balance: {balance}")
                    positions = await client.get_positions()
                    print(f"    positions: {positions}")
                    # Get current ETH price
                    ticker = await client.get_ticker("ETH-USDT-SWAP")
                    print(f"    ETH-USDT-SWAP ticker: {ticker}")
                except Exception as e:
                    print(f"    API call failed: {e}")
                finally:
                    try:
                        await client.close()
                    except Exception:
                        pass
            except Exception as e:
                print(f"  id={a.id} decrypt error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
