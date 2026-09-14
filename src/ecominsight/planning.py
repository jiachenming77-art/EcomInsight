from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Dict, Optional, Set

import yaml

from .models import AnalysisPlan, ComparisonWindow, PlanStep
from .semantic import MetricRegistry

ALLOWED_OPS = {
    "metric_summary",
    "metric_compare",
    "trend",
    "anomaly_scan",
    "driver_tree_decompose",
    "ratio_decompose",
    "contribution",
    "drilldown",
    "funnel",
    "cohort",
    "rfm",
    "repurchase",
    "product_performance",
}


class PlanBuilder:
    def __init__(self, templates_path: str | Path):
        payload = yaml.safe_load(Path(templates_path).read_text(encoding="utf-8")) or {}
        self.templates: Dict[str, dict] = payload.get("templates", {})

    def build(
        self,
        question: str,
        current: Optional[Iterable[str]] = None,
        baseline: Optional[Iterable[str]] = None,
    ) -> AnalysisPlan:
        lower = question.lower()
        change_words = ("为什么", "原因", "下降", "上涨", "变化", "why", "drop", "increase", "change")
        template_name = "gmv_change" if any(word in lower for word in change_words) and ("gmv" in lower or "销售" in lower or "成交" in lower) else "overview"
        template = self.templates[template_name]
        requires_comparison = template_name == "gmv_change"
        comparison = None
        confirmation_required = False
        confirmation_reason = None
        assumptions = []
        if requires_comparison:
            if current and baseline:
                comparison = ComparisonWindow(current=list(current), baseline=list(baseline))
            else:
                confirmation_required = True
                confirmation_reason = "指标变化分析需要明确当前期和基准期"
        steps = [PlanStep(**step) for step in template["steps"]]
        return AnalysisPlan(
            question=question,
            objective=template["objective"],
            target_metric=template["target_metric"],
            comparison=comparison,
            steps=steps,
            assumptions=assumptions,
            required_fields=["event_time", "amount", "order_id", "user_id"],
            confirmation_required=confirmation_required,
            confirmation_reason=confirmation_reason,
        )


class PlanValidator:
    def __init__(self, registry: MetricRegistry, available_fields: Set[str], allowed_dimensions: Optional[Set[str]] = None):
        self.registry = registry
        self.available_fields = available_fields
        self.allowed_dimensions = allowed_dimensions or {"channel", "customer_type", "category_id", "product_id"}

    def validate(self, plan: AnalysisPlan) -> None:
        if plan.target_metric not in self.registry.metrics:
            raise ValueError(f"unknown target metric: {plan.target_metric}")
        missing = set(plan.required_fields) - self.available_fields
        if missing:
            raise ValueError(f"plan missing fields: {sorted(missing)}")
        seen = set()
        for step in plan.steps:
            if step.id in seen:
                raise ValueError(f"duplicate step id: {step.id}")
            seen.add(step.id)
            if step.op not in ALLOWED_OPS:
                raise ValueError(f"operation not allowed: {step.op}")
            if step.metric and step.metric not in self.registry.metrics:
                raise ValueError(f"unknown metric: {step.metric}")
            if step.op in {"contribution", "drilldown", "product_performance"}:
                invalid_dimensions = set(step.dimensions) - self.allowed_dimensions
                if invalid_dimensions:
                    raise ValueError(f"dimensions not allowed: {sorted(invalid_dimensions)}")
        if (
            any(step.op in {"metric_compare", "driver_tree_decompose", "contribution", "drilldown"} for step in plan.steps)
            and plan.comparison is None
            and not plan.confirmation_required
        ):
            raise ValueError("comparison plan requires explicit windows")


def contains_code_injection(text: str) -> bool:
    patterns = [r"\bimport\s+os\b", r"subprocess", r"rm\s+-rf", r"__import__", r"```(?:python|bash|sh)"]
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)
