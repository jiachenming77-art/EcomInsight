from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import yaml

from .analytics import (
    cohort_retention,
    contribution_analysis,
    driver_tree_decompose,
    funnel_analysis,
    metric_compare,
    product_performance,
    repurchase_analysis,
    rfm_analysis,
)
from .evidence import evidence_for_result, verify
from .models import AnalysisPlan, Claim, RunStatus, SemanticContract
from .planning import PlanBuilder, PlanValidator, contains_code_injection
from .quality import profile_quality
from .reporting import render_report
from .runs import RunManager
from .semantic import FieldMapper, MetricRegistry


class EcomInsightPipeline:
    def __init__(self, project_root: str | Path):
        self.root = Path(project_root)
        self.mapper = FieldMapper(self.root / "configs/field_aliases.yaml")
        self.registry = MetricRegistry.from_yaml(self.root / "configs/metric_definitions.yaml")
        self.planner = PlanBuilder(self.root / "configs/analysis_templates.yaml")
        self.runs = RunManager(self.root / "runs")
        self.trees = yaml.safe_load((self.root / "configs/kpi_driver_trees.yaml").read_text(encoding="utf-8"))["trees"]

    def prepare(self, raw: pd.DataFrame, contract: Optional[SemanticContract] = None) -> tuple[pd.DataFrame, SemanticContract, Dict[str, Any]]:
        contract = contract or self.mapper.infer(raw)
        frame = self.mapper.apply(raw, contract)
        quality = profile_quality(frame)
        return frame, contract, quality

    def build_plan(self, question: str, current: Optional[Iterable[str]] = None, baseline: Optional[Iterable[str]] = None) -> AnalysisPlan:
        if contains_code_injection(question):
            raise ValueError("question contains disallowed code or shell instructions")
        return self.planner.build(question, current, baseline)

    def execute(self, raw: pd.DataFrame, plan: AnalysisPlan, contract: Optional[SemanticContract] = None) -> Dict[str, Any]:
        frame, contract, quality = self.prepare(raw, contract)
        PlanValidator(self.registry, set(frame.columns)).validate(plan)
        metric_snapshot = {key: item.model_dump(mode="json") for key, item in self.registry.metrics.items()}
        manifest = self.runs.create(frame, contract, metric_snapshot, plan, self.root)
        self.runs.update_status(manifest, RunStatus.validated)
        if quality["blocking"]:
            self.runs.write(manifest.run_id, "quality_report.json", quality)
            self.runs.update_status(manifest, RunStatus.blocked, "data quality gate blocked execution")
            return {"run_id": manifest.run_id, "status": "blocked", "quality": quality}
        self.runs.update_status(manifest, RunStatus.running)
        results: Dict[str, Any] = {"summary": self.registry.compute_many(frame, ["gmv", "paid_orders", "paid_users", "aov"])}
        evidence = []
        try:
            for step in plan.steps:
                if step.op == "metric_summary":
                    result = {step.metric: self.registry.compute(frame, step.metric)}
                elif step.op == "metric_compare":
                    result = metric_compare(self.registry, frame, step.metric or plan.target_metric, plan.comparison.current, plan.comparison.baseline)
                elif step.op == "driver_tree_decompose":
                    result = driver_tree_decompose(self.registry, frame, self.trees[step.tree], plan.comparison.current, plan.comparison.baseline)
                elif step.op in {"contribution", "drilldown"}:
                    result = {
                        dimension: contribution_analysis(self.registry, frame, plan.target_metric, dimension, plan.comparison.current, plan.comparison.baseline, step.top_n)
                        for dimension in step.dimensions
                    }
                elif step.op == "rfm":
                    result = rfm_analysis(frame)
                elif step.op == "cohort":
                    result = cohort_retention(frame)
                elif step.op == "repurchase":
                    result = repurchase_analysis(frame)
                elif step.op == "product_performance":
                    dimension = step.dimensions[0] if step.dimensions else "product_id"
                    result = product_performance(frame, dimension, step.top_n)
                elif step.op == "funnel":
                    result = funnel_analysis(frame, step.dimensions)
                else:
                    result = {"status": "not_implemented", "op": step.op}
                results[step.id + "_" + step.op] = result
                metric = step.metric or plan.target_metric
                evidence.append(evidence_for_result(
                    manifest.run_id,
                    step.id,
                    metric,
                    self.registry.get(metric).label,
                    result,
                    self.registry.get(metric).unit,
                    len(frame),
                    step.op,
                    manifest.dataset_hash,
                    len(evidence) + 1,
                ))
            claims = self._claims(plan, results, evidence)
            verification = verify(evidence, claims, manifest.run_id)
            self.runs.write(manifest.run_id, "quality_report.json", quality)
            self.runs.write(manifest.run_id, "results/results.json", results)
            self.runs.write(manifest.run_id, "evidence.json", [item.model_dump(mode="json") for item in evidence])
            self.runs.write(manifest.run_id, "claims.json", [item.model_dump(mode="json") for item in claims])
            self.runs.write(manifest.run_id, "verification.json", verification)
            self.runs.update_status(manifest, RunStatus.completed)
            report_path = render_report(self.runs.path(manifest.run_id) / "report.html", manifest, plan, quality, results, evidence, claims, verification)
            return {"run_id": manifest.run_id, "status": "completed", "results": results, "quality": quality, "verification": verification, "report": str(report_path)}
        except Exception as error:
            self.runs.update_status(manifest, RunStatus.failed, str(error))
            self.runs.write(manifest.run_id, "execution_error.json", {"type": type(error).__name__, "message": str(error)})
            raise

    @staticmethod
    def _claims(plan: AnalysisPlan, results: Dict[str, Any], evidence: list) -> list[Claim]:
        claims = []
        comparison_result = next((value for key, value in results.items() if key.endswith("metric_compare")), None)
        if comparison_result:
            direction = "上升" if comparison_result["delta"] > 0 else "下降" if comparison_result["delta"] < 0 else "持平"
            claims.append(Claim(
                claim_id="C-001",
                text=f"{plan.target_metric} 当前期较基准期{direction} {abs(comparison_result['delta']):,.2f}",
                level="comparison",
                evidence_ids=[evidence[0].evidence_id] if evidence else [],
            ))
        return claims
