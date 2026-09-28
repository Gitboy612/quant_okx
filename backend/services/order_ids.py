"""OKX 客户端订单号（clOrdId）生成与约束。

OKX V5 clOrdId：字母数字，最长 32 字符。用于超时重试幂等与本地订单意图关联。
"""

from __future__ import annotations

import secrets
import time


def generate_cl_ord_id(strategy_instance_id: int | None = None) -> str:
    """生成唯一 clOrdId（<=32 字符，字母数字）。

    格式：q{sid}{ms_base36}{rand}，截断保证符合 OKX 限制。
    """
    sid = int(strategy_instance_id or 0)
    ms = int(time.time() * 1000)
    ms_part = _to_base36(ms)
    rand_part = secrets.token_hex(3)  # 6 hex chars
    raw = f"q{sid}{ms_part}{rand_part}"
    # OKX 仅允许字母数字；去掉可能的非字母数字（base36 已安全）
    cleaned = "".join(ch for ch in raw if ch.isalnum())
    return cleaned[:32]


def _to_base36(n: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n <= 0:
        return "0"
    out = []
    while n:
        n, rem = divmod(n, 36)
        out.append(alphabet[rem])
    return "".join(reversed(out))
