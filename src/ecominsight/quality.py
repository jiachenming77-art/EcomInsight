from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd


def profile_quality(frame: pd.DataFrame) -> Dict[str, Any]:
    rows = len(frame)
    issues: List[Dict[str, Any]] = []
    completeness_scores = []
    for field in frame.columns:
        missing_rate = float(frame[field].isna().mean()) if rows else 1.0
        completeness_scores.append(1 - missing_rate)
        if missing_rate > 0:
            critical = str(field) in {"user_id", "order_id", "event_time", "amount"}
            severity = "error" if critical and missing_rate >= 0.5 else "warning"
            issues.append({
                "rule_id": "missing_values",
                "severity": severity,
                "field": str(field),
                "description": f"字段缺失率为 {missing_rate:.1%}",
                "impact": "依赖该字段的指标可能降级或不可用",
                "recommendation": "核对数据源并确认空值处理口径",
            })
    duplicates = int(frame.duplicated().sum())
    if duplicates:
        issues.append({
            "rule_id": "duplicate_rows",
            "severity": "warning",
            "field": None,
            "description": f"存在 {duplicates} 行完全重复记录",
            "impact": "求和与计数指标可能被高估",
            "recommendation": "确认业务粒度后去重",
        })
    if "order_id" in frame:
        duplicate_orders = int(frame["order_id"].dropna().duplicated().sum())
        if duplicate_orders:
            issues.append({
                "rule_id": "duplicate_order_id",
                "severity": "warning",
                "field": "order_id",
                "description": f"订单号有 {duplicate_orders} 个重复记录",
                "impact": "需确认订单明细粒度，订单数将按去重口径计算",
                "recommendation": "检查是否为一单多商品明细",
            })
    if "event_time" in frame:
        invalid_dates = int(frame["event_time"].isna().sum())
        if invalid_dates:
            issues.append({
                "rule_id": "invalid_event_time",
                "severity": "error" if invalid_dates / max(rows, 1) >= 0.5 else "warning",
                "field": "event_time",
                "description": f"有 {invalid_dates} 行时间无法解析",
                "impact": "趋势、Cohort 与观察窗分析受影响",
                "recommendation": "统一时间格式和时区",
            })
    if "amount" in frame:
        invalid_amount = int((pd.to_numeric(frame["amount"], errors="coerce") <= 0).sum())
        if invalid_amount:
            issues.append({
                "rule_id": "non_positive_amount",
                "severity": "warning",
                "field": "amount",
                "description": f"有 {invalid_amount} 行金额小于或等于零",
                "impact": "默认从有效支付 GMV 中排除",
                "recommendation": "确认退款、冲销和赠品口径",
            })
    completeness = 100 * (sum(completeness_scores) / len(completeness_scores) if completeness_scores else 0)
    uniqueness = 100 * (1 - duplicates / max(rows, 1))
    validity_penalty = sum(8 for issue in issues if issue["severity"] == "error") + sum(2 for issue in issues if issue["severity"] == "warning")
    validity = max(0.0, 100.0 - validity_penalty)
    score = round(0.45 * completeness + 0.25 * uniqueness + 0.30 * validity, 1)
    return {
        "rows": rows,
        "columns": len(frame.columns),
        "score": score,
        "dimensions": {
            "completeness": round(completeness, 1),
            "uniqueness": round(uniqueness, 1),
            "validity": round(validity, 1),
        },
        "issues": issues,
        "blocking": any(issue["severity"] == "error" for issue in issues),
    }
