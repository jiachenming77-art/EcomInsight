from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .semantic import MetricRegistry


def valid_orders(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "order_status" in result:
        accepted = {"paid", "completed", "支付成功", "已完成"}
        result = result[result["order_status"].astype(str).str.lower().isin(accepted)]
    if "amount" in result:
        result = result[pd.to_numeric(result["amount"], errors="coerce") > 0]
    return result


def rfm_analysis(frame: pd.DataFrame, reference_date: Optional[pd.Timestamp] = None) -> Dict[str, Any]:
    required = {"user_id", "order_id", "event_time", "amount"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"rfm missing fields: {sorted(missing)}")
    work = valid_orders(frame).dropna(subset=list(required)).copy()
    reference = pd.Timestamp(reference_date) if reference_date is not None else work["event_time"].max() + pd.Timedelta(days=1)
    grouped = work.groupby("user_id").agg(
        last_purchase=("event_time", "max"),
        frequency=("order_id", "nunique"),
        monetary=("amount", "sum"),
    )
    grouped["recency"] = (reference - grouped["last_purchase"]).dt.days

    def score(series: pd.Series, reverse: bool = False) -> pd.Series:
        ranks = series.rank(method="first", pct=True)
        values = np.ceil(ranks * 4).clip(1, 4).astype(int)
        return 5 - values if reverse else values

    grouped["r_score"] = score(grouped["recency"], reverse=True)
    grouped["f_score"] = score(grouped["frequency"])
    grouped["m_score"] = score(grouped["monetary"])
    grouped["segment"] = np.select(
        [
            (grouped.r_score >= 3) & (grouped.f_score >= 3) & (grouped.m_score >= 3),
            (grouped.r_score >= 3) & (grouped.f_score >= 2),
            (grouped.r_score <= 2) & (grouped.f_score >= 3),
        ],
        ["high_value", "potential", "at_risk"],
        default="general",
    )
    grouped = grouped.reset_index()
    summary = grouped.groupby("segment", as_index=False).agg(
        users=("user_id", "nunique"),
        gmv=("monetary", "sum"),
        avg_orders=("frequency", "mean"),
    )
    total_users, total_gmv = len(grouped), float(grouped["monetary"].sum())
    summary["user_share"] = summary["users"] / total_users if total_users else 0
    summary["gmv_share"] = summary["gmv"] / total_gmv if total_gmv else 0
    return {
        "reference_date": reference.isoformat(),
        "users": grouped.to_dict("records"),
        "segments": summary.to_dict("records"),
        "reconciliation": {"users": total_users, "gmv": total_gmv},
    }


def funnel_analysis(
    frame: pd.DataFrame,
    stages: Iterable[str],
    window_hours: Optional[int] = None,
) -> Dict[str, Any]:
    required = {"user_id", "event_type", "event_time"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"funnel missing fields: {sorted(missing)}")
    ordered_stages = list(stages)
    if len(ordered_stages) < 2:
        raise ValueError("funnel requires at least two stages")
    work = frame.dropna(subset=list(required)).sort_values(["user_id", "event_time"])
    completed_at: Dict[Any, pd.Timestamp] = {}
    counts = []
    for index, stage in enumerate(ordered_stages):
        reached: Dict[Any, pd.Timestamp] = {}
        for user_id, group in work.groupby("user_id", sort=False):
            events = group[group["event_type"].astype(str) == str(stage)]["event_time"]
            if index == 0 and not events.empty:
                reached[user_id] = events.iloc[0]
            elif user_id in completed_at:
                valid = events[events >= completed_at[user_id]]
                if window_hours is not None:
                    valid = valid[valid <= completed_at[user_id] + pd.Timedelta(hours=window_hours)]
                if not valid.empty:
                    reached[user_id] = valid.iloc[0]
        previous = counts[-1]["users"] if counts else None
        users = len(reached)
        counts.append({
            "stage": stage,
            "users": users,
            "rate_from_previous": users / previous if previous else None,
            "loss_from_previous": previous - users if previous is not None else None,
        })
        completed_at = reached
    first = counts[0]["users"]
    for item in counts:
        item["overall_rate"] = item["users"] / first if first else None
    return {"stages": counts, "window_hours": window_hours}


def cohort_retention(frame: pd.DataFrame, frequency: str = "M") -> Dict[str, Any]:
    required = {"user_id", "event_time"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"cohort missing fields: {sorted(missing)}")
    work = frame.dropna(subset=list(required)).copy()
    period_code = {"D": "D", "W": "W", "M": "M"}.get(frequency.upper())
    if period_code is None:
        raise ValueError("frequency must be D, W or M")
    work["period"] = work["event_time"].dt.to_period(period_code)
    work["cohort"] = work.groupby("user_id")["period"].transform("min")
    if period_code == "M":
        work["age"] = (work["period"].dt.year - work["cohort"].dt.year) * 12 + work["period"].dt.month - work["cohort"].dt.month
    else:
        work["age"] = ((work["period"].dt.start_time - work["cohort"].dt.start_time).dt.days / (7 if period_code == "W" else 1)).astype(int)
    counts = work.groupby(["cohort", "age"])["user_id"].nunique().unstack()
    sizes = counts.get(0, pd.Series(dtype=float))
    retention = counts.div(sizes, axis=0)
    latest = work["period"].max()
    rows = []
    for cohort, values in retention.iterrows():
        mature_age = int((latest.start_time - cohort.start_time).days / (30 if period_code == "M" else 7 if period_code == "W" else 1))
        row = {"cohort": str(cohort), "size": int(sizes.loc[cohort]), "retention": {}}
        for age, value in values.items():
            row["retention"][str(int(age))] = float(value) if int(age) <= mature_age and pd.notna(value) else None
        rows.append(row)
    return {"frequency": period_code, "cohorts": rows}


def repurchase_analysis(frame: pd.DataFrame, windows: Iterable[int] = (30, 60, 90)) -> Dict[str, Any]:
    required = {"user_id", "order_id", "event_time"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"repurchase missing fields: {sorted(missing)}")
    work = valid_orders(frame).dropna(subset=list(required)).drop_duplicates(["user_id", "order_id"]).sort_values(["user_id", "event_time"])
    purchases = work.groupby("user_id")["event_time"].apply(list)
    buyers = len(purchases)
    repeats = int(sum(len(times) >= 2 for times in purchases))
    intervals = [
        (times[index] - times[index - 1]).days
        for times in purchases
        for index in range(1, len(times))
    ]
    data_end = work["event_time"].max()
    window_results = {}
    for days in windows:
        mature = [times for times in purchases if times[0] <= data_end - pd.Timedelta(days=days)]
        repeated = sum(any(time <= times[0] + pd.Timedelta(days=days) for time in times[1:]) for times in mature)
        window_results[str(days)] = {
            "mature_buyers": len(mature),
            "repeat_buyers": int(repeated),
            "rate": repeated / len(mature) if mature else None,
        }
    return {
        "buyers": buyers,
        "repeat_buyers": repeats,
        "repurchase_rate": repeats / buyers if buyers else None,
        "mean_interval_days": float(np.mean(intervals)) if intervals else None,
        "median_interval_days": float(np.median(intervals)) if intervals else None,
        "windows": window_results,
    }


def product_performance(frame: pd.DataFrame, dimension: str = "product_id", top_n: int = 10) -> Dict[str, Any]:
    required = {dimension, "order_id", "user_id", "amount"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"product analysis missing fields: {sorted(missing)}")
    work = valid_orders(frame).dropna(subset=[dimension])
    aggregations = {
        "gmv": ("amount", "sum"),
        "orders": ("order_id", "nunique"),
        "buyers": ("user_id", "nunique"),
    }
    if "quantity" in work:
        aggregations["units"] = ("quantity", "sum")
    grouped = work.groupby(dimension, as_index=False).agg(**aggregations)
    grouped["aov"] = grouped["gmv"] / grouped["orders"].replace(0, np.nan)
    total_gmv = float(grouped["gmv"].sum())
    grouped["gmv_share"] = grouped["gmv"] / total_gmv if total_gmv else 0
    grouped = grouped.sort_values("gmv", ascending=False).head(top_n)
    return {"dimension": dimension, "total_gmv": total_gmv, "rows": grouped.to_dict("records")}


def split_periods(frame: pd.DataFrame, current: List[str], baseline: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if "event_time" not in frame:
        raise ValueError("period comparison requires event_time")
    current_frame = frame[frame["event_time"].between(pd.Timestamp(current[0]), pd.Timestamp(current[1]) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1))]
    baseline_frame = frame[frame["event_time"].between(pd.Timestamp(baseline[0]), pd.Timestamp(baseline[1]) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1))]
    return current_frame, baseline_frame


def metric_compare(registry: MetricRegistry, frame: pd.DataFrame, metric: str, current: List[str], baseline: List[str]) -> Dict[str, Any]:
    current_frame, baseline_frame = split_periods(frame, current, baseline)
    current_value = registry.compute(current_frame, metric)
    baseline_value = registry.compute(baseline_frame, metric)
    delta = current_value - baseline_value if current_value is not None and baseline_value is not None else None
    change_rate = delta / baseline_value if delta is not None and baseline_value else None
    return {"metric": metric, "baseline": baseline_value, "current": current_value, "delta": delta, "change_rate": change_rate}


def contribution_analysis(
    registry: MetricRegistry,
    frame: pd.DataFrame,
    metric: str,
    dimension: str,
    current: List[str],
    baseline: List[str],
    top_n: int = 10,
    min_sample: int = 1,
) -> Dict[str, Any]:
    if dimension not in frame:
        return {"dimension": dimension, "status": "unavailable", "rows": []}
    current_frame, baseline_frame = split_periods(frame, current, baseline)
    groups = set(current_frame[dimension].dropna().unique()) | set(baseline_frame[dimension].dropna().unique())
    rows = []
    for group in groups:
        current_group = current_frame[current_frame[dimension] == group]
        baseline_group = baseline_frame[baseline_frame[dimension] == group]
        sample_size = len(current_group) + len(baseline_group)
        if sample_size < min_sample:
            continue
        current_value = registry.compute(current_group, metric)
        baseline_value = registry.compute(baseline_group, metric)
        delta = current_value - baseline_value
        rows.append({"group": str(group), "baseline": baseline_value, "current": current_value, "delta": delta, "sample_size": sample_size})
    gap = sum(item["delta"] for item in rows)
    for item in rows:
        item["share_of_gap"] = item["delta"] / gap if gap else None
    rows.sort(key=lambda item: abs(item["delta"]), reverse=True)
    return {"dimension": dimension, "status": "ok", "gap": gap, "rows": rows[:top_n]}


def symmetric_multiplicative_decomposition(baseline: List[float], current: List[float]) -> List[float]:
    if len(baseline) != len(current) or not baseline:
        raise ValueError("driver vectors must have equal non-zero length")
    total_change = math.prod(current) - math.prod(baseline)
    raw = []
    for index in range(len(baseline)):
        others = [0.5 * (baseline[j] + current[j]) for j in range(len(baseline)) if j != index]
        raw.append((current[index] - baseline[index]) * math.prod(others))
    residual = total_change - sum(raw)
    return [value + residual / len(raw) for value in raw]


def driver_tree_decompose(
    registry: MetricRegistry,
    frame: pd.DataFrame,
    tree: Dict[str, Any],
    current: List[str],
    baseline: List[str],
) -> Dict[str, Any]:
    children = [item["metric"] for item in tree.get("children", [])]
    if not children:
        raise ValueError("driver tree requires children")
    current_frame, baseline_frame = split_periods(frame, current, baseline)
    current_values = [registry.compute(current_frame, key) for key in children]
    baseline_values = [registry.compute(baseline_frame, key) for key in children]
    if any(value is None for value in current_values + baseline_values):
        return {"status": "degraded", "metric": tree["metric"], "drivers": []}
    relation = tree.get("relation", "multiply")
    if relation == "multiply":
        contributions = symmetric_multiplicative_decomposition(baseline_values, current_values)
    elif relation == "add":
        contributions = [current_value - baseline_value for current_value, baseline_value in zip(current_values, baseline_values)]
    else:
        raise ValueError(f"unsupported driver relation: {relation}")
    target = metric_compare(registry, frame, tree["metric"], current, baseline)
    drivers = [
        {"metric": key, "baseline": before, "current": after, "contribution": contribution}
        for key, before, after, contribution in zip(children, baseline_values, current_values, contributions)
    ]
    reconciliation_error = target["delta"] - sum(item["contribution"] for item in drivers)
    return {"status": "ok", "metric": tree["metric"], "target": target, "drivers": drivers, "reconciliation_error": reconciliation_error}
