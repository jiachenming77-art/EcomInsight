from pathlib import Path

import pandas as pd
import pytest
import yaml

from ecominsight.analytics import (
    cohort_retention,
    contribution_analysis,
    driver_tree_decompose,
    funnel_analysis,
    product_performance,
    repurchase_analysis,
    rfm_analysis,
)
from ecominsight.semantic import FieldMapper, MetricRegistry

ROOT = Path(__file__).resolve().parents[2]


def prepared(orders):
    mapper = FieldMapper(ROOT / "configs/field_aliases.yaml")
    return mapper.apply(orders, mapper.infer(orders))


def test_core_ecommerce_analytics(orders):
    frame = prepared(orders)
    rfm = rfm_analysis(frame)
    assert rfm["reconciliation"]["users"] == 4
    assert rfm["reconciliation"]["gmv"] == 1570
    repurchase = repurchase_analysis(frame)
    assert repurchase["repurchase_rate"] == 1
    assert repurchase["windows"]["30"]["mature_buyers"] == 4
    products = product_performance(frame)
    assert products["total_gmv"] == 1570
    cohort = cohort_retention(frame)
    assert cohort["cohorts"][0]["retention"]["0"] == 1


def test_ordered_funnel_excludes_wrong_order():
    events = pd.DataFrame({
        "user_id": ["u1", "u1", "u1", "u2", "u2"],
        "event_type": ["view", "cart", "pay", "pay", "view"],
        "event_time": pd.to_datetime(["2026-01-01 10:00", "2026-01-01 10:05", "2026-01-01 10:10", "2026-01-01 09:00", "2026-01-01 10:00"]),
    })
    result = funnel_analysis(events, ["view", "cart", "pay"])
    assert [row["users"] for row in result["stages"]] == [2, 1, 1]


def test_driver_tree_and_contribution_close(orders):
    frame = prepared(orders)
    registry = MetricRegistry.from_yaml(ROOT / "configs/metric_definitions.yaml")
    tree = yaml.safe_load((ROOT / "configs/kpi_driver_trees.yaml").read_text())["trees"]["gmv_v1"]
    result = driver_tree_decompose(registry, frame, tree, ["2026-08-01", "2026-08-31"], ["2026-07-01", "2026-07-31"])
    assert result["reconciliation_error"] == pytest.approx(0, abs=1e-9)
    channel = contribution_analysis(registry, frame, "gmv", "channel", ["2026-08-01", "2026-08-31"], ["2026-07-01", "2026-07-31"])
    assert channel["gap"] == -430
    assert sum(row["delta"] for row in channel["rows"]) == -430
