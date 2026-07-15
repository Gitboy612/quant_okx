"""关闭遗留的 ETH-USDT-SWAP 仓位（strategy #1 stopped 后的孤儿仓位）。"""
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
            # 1. 查看当前持仓
            positions = await client.get_positions()
            print(f"Current positions count: {len(positions) if positions else 0}")
            for p in positions or []:
                print(f"  instId={p.get('instId')} pos={p.get('pos')} mgnMode={p.get('mgnMode')} posSide={p.get('posSide')} upl={p.get('upl')}")

            # 2. 关闭 ETH-USDT-SWAP 仓位
            for p in positions or []:
                if p.get('instId') == 'ETH-USDT-SWAP' and float(p.get('pos', 0)) != 0:
                    print(f"\nClosing position: {p.get('instId')} mgnMode={p.get('mgnMode')}")
                    try:
                        resp = await client.trade.close_positions(
                            instId=p.get('instId'),
                            mgnMode=p.get('mgnMode'),
                            posSide=p.get('posSide') if p.get('posSide') != 'net' else None,
                        )
                        print(f"  Close response: {resp}")
                    except Exception as e:
                        print(f"  Close exception: {e}")

            # 3. 验证已平仓
            positions_after = await client.get_positions()
            print(f"\nPositions after close: {len(positions_after) if positions_after else 0}")
            for p in positions_after or []:
                if float(p.get('pos', 0)) != 0:
                    print(f"  Still open: {p.get('instId')} pos={p.get('pos')}")

            # 4. 查看余额
            balance = await client.get_balance()
            usdt = next((d for d in balance.get('details', []) if d.get('ccy') == 'USDT'), None)
            if usdt:
                print(f"\nUSDT balance after close: eq={usdt.get('eq')} availBal={usdt.get('availBal')}")
        finally:
            try:
                await client.close()
            except Exception:
                pass
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
