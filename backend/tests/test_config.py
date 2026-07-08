import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models.account import Account
from services.okx_client import OKXClient
from services.okx.base import OKXBaseClient


async def get_test_client() -> OKXClient:
    db = SessionLocal()
    try:
        account = db.query(Account).filter(Account.trade_mode == "demo").first()
        if not account:
            raise Exception("请先在前端添加模拟盘账户")
        client = OKXClient(
            api_key_encrypted=account.api_key_encrypted,
            secret_encrypted=account.secret_key_encrypted,
            passphrase_encrypted=account.passphrase_encrypted,
            trade_mode=account.trade_mode,
            account_name=account.name,
        )
        return client
    finally:
        db.close()


def get_public_client():
    base_client = OKXBaseClient(
        api_key="",
        secret_key="",
        passphrase="",
        trade_mode="demo",
    )
    return base_client


class TestRunner:
    def __init__(self):
        self.passed = 0
        self.total = 0
        self.failures = []

    def check(self, name: str, ok: bool, msg: str = "", data_preview: str = ""):
        print(f"测试: {name}")
        self.total += 1
        if ok:
            self.passed += 1
            print(f"  PASS: {data_preview}")
        else:
            self.failures.append((name, msg or "检查失败"))
            print(f"  FAIL: {msg or '检查失败'}")

    async def run_test(self, name: str, coro, validate=None):
        print(f"测试: {name}")
        self.total += 1
        try:
            result = await coro
            ok = True
            msg = ""
            if isinstance(result, dict) and "code" in result:
                if result.get("code") != "0":
                    ok = False
                    msg = f"code={result.get('code')} msg={result.get('msg', '')}"
            if ok and validate:
                ok, msg = validate(result)
            if ok:
                self.passed += 1
                preview = str(result)[:200] if result else ""
                print(f"  PASS: code=0 {preview}")
            else:
                self.failures.append((name, msg or f"验证失败: {result}"))
                print(f"  FAIL: {msg or '验证失败'}")
        except Exception as e:
            self.failures.append((name, str(e)))
            print(f"  FAIL: {str(e)}")

    def print_summary(self, module_name: str):
        print(f"\n结果: {self.passed}/{self.total} 通过")
        if self.failures:
            print("失败列表:")
            for name, err in self.failures:
                print(f"  - {name}: {err}")
        return self.passed, self.total, self.failures
