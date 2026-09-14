from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def orders() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "用户编号": ["u1", "u1", "u2", "u2", "u3", "u3", "u4", "u4"],
            "订单编号": ["o1", "o2", "o3", "o4", "o5", "o6", "o7", "o8"],
            "支付时间": pd.to_datetime([
                "2026-07-05", "2026-08-05", "2026-07-10", "2026-08-12",
                "2026-07-15", "2026-08-15", "2026-07-20", "2026-08-20",
            ]),
            "支付金额": [100, 120, 200, 100, 300, 150, 400, 200],
            "购买数量": [1, 1, 2, 1, 3, 1, 4, 2],
            "支付状态": ["paid"] * 8,
            "商品编号": ["p1", "p1", "p2", "p2", "p3", "p3", "p4", "p4"],
            "品类": ["A", "A", "B", "B", "C", "C", "D", "D"],
            "渠道": ["search", "search", "ads", "ads", "ads", "ads", "direct", "direct"],
            "用户类型": ["old", "old", "new", "new", "new", "new", "old", "old"],
        }
    )
