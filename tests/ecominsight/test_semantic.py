from pathlib import Path

import pandas as pd
import pytest

from ecominsight.semantic import FieldMapper, MetricRegistry

ROOT = Path(__file__).resolve().parents[2]


def test_field_mapping_and_metric_reconciliation(orders):
    mapper = FieldMapper(ROOT / "configs/field_aliases.yaml")
    contract = mapper.infer(orders)
    frame = mapper.apply(orders, contract)
    assert contract.source_for("user_id") == "用户编号"
    registry = MetricRegistry.from_yaml(ROOT / "configs/metric_definitions.yaml")
    assert registry.compute(frame, "gmv") == 1570
    assert registry.compute(frame, "paid_orders") == 8
    assert registry.compute(frame, "paid_users") == 4
    assert registry.compute(frame, "aov") == pytest.approx(196.25)


def test_unknown_metric_rejected():
    registry = MetricRegistry.from_yaml(ROOT / "configs/metric_definitions.yaml")
    with pytest.raises(KeyError):
        registry.compute(pd.DataFrame(), "profit")
