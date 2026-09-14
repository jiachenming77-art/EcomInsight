"""Generate a small, privacy-safe EcomInsight Analysis Run."""

from pathlib import Path

import pandas as pd

from ecominsight.pipeline import EcomInsightPipeline

ROOT = Path(__file__).resolve().parents[1]

orders = pd.DataFrame(
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

pipeline = EcomInsightPipeline(ROOT)
plan = pipeline.build_plan(
    "为什么 8 月 GMV 比 7 月下降？",
    current=["2026-08-01", "2026-08-31"],
    baseline=["2026-07-01", "2026-07-31"],
)
result = pipeline.execute(orders, plan)
print(result["run_id"])
print(result["verification"]["status"])
print(result["report"])
