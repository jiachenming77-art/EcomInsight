from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd
import yaml

from .models import FieldMapping, MetricDefinition, SemanticContract


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value).lower())


class FieldMapper:
    def __init__(self, aliases_path: str | Path):
        payload = yaml.safe_load(Path(aliases_path).read_text(encoding="utf-8"))
        self.aliases: Dict[str, List[str]] = payload.get("fields", {})

    def infer(self, frame: pd.DataFrame, threshold: float = 0.85) -> SemanticContract:
        mappings: List[FieldMapping] = []
        used: Set[str] = set()
        for semantic, aliases in self.aliases.items():
            candidates = []
            semantic_norm = _normalise(semantic)
            for column in map(str, frame.columns):
                column_norm = _normalise(column)
                alias_norms = {_normalise(alias) for alias in aliases}
                if column_norm == semantic_norm:
                    candidates.append((1.0, column, "标准字段精确匹配"))
                elif column_norm in alias_norms:
                    candidates.append((0.95, column, "字段别名精确匹配"))
                elif any(alias and alias in column_norm for alias in alias_norms):
                    candidates.append((0.75, column, "字段名包含别名"))
            candidates.sort(reverse=True)
            if candidates and candidates[0][1] not in used:
                confidence, source, reason = candidates[0]
                mappings.append(
                    FieldMapping(
                        semantic=semantic,
                        source=source,
                        confidence=confidence,
                        reason=reason,
                        confirmed=confidence >= threshold,
                    )
                )
                used.add(source)
        return SemanticContract(mappings=mappings)

    @staticmethod
    def apply(frame: pd.DataFrame, contract: SemanticContract) -> pd.DataFrame:
        rename = {
            mapping.source: mapping.semantic
            for mapping in contract.mappings
            if mapping.confirmed
        }
        result = frame.rename(columns=rename).copy()
        if "event_time" in result:
            result["event_time"] = pd.to_datetime(result["event_time"], errors="coerce")
        for field in ("amount", "quantity"):
            if field in result:
                result[field] = pd.to_numeric(result[field], errors="coerce")
        return result


class MetricRegistry:
    ALLOWED_AGGREGATIONS = {"sum", "count", "count_distinct", "mean", "min", "max"}
    ALLOWED_FILTERS = {"eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte"}

    def __init__(self, metrics: Dict[str, MetricDefinition], config_path: Optional[Path] = None):
        self.metrics = metrics
        self.config_path = config_path
        self._validate_dependencies()

    @classmethod
    def from_yaml(cls, path: str | Path) -> MetricRegistry:
        config_path = Path(path)
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        metrics = {
            key: MetricDefinition(key=key, **definition)
            for key, definition in payload.get("metrics", {}).items()
        }
        if not metrics:
            raise ValueError("metric registry cannot be empty")
        return cls(metrics, config_path)

    def _expression_names(self, expression: str) -> Set[str]:
        tree = ast.parse(expression, mode="eval")
        allowed = (ast.Expression, ast.BinOp, ast.Name, ast.Load, ast.Div, ast.Mult, ast.Add, ast.Sub)
        if any(not isinstance(node, allowed) for node in ast.walk(tree)):
            raise ValueError(f"unsupported metric expression: {expression}")
        return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    def dependencies(self, key: str) -> Set[str]:
        metric = self.get(key)
        return self._expression_names(metric.expression) if metric.expression else set()

    def _validate_dependencies(self) -> None:
        visiting: Set[str] = set()
        visited: Set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise ValueError(f"cyclic metric dependency at {key}")
            if key in visited:
                return
            visiting.add(key)
            metric = self.get(key)
            if metric.aggregation and metric.aggregation not in self.ALLOWED_AGGREGATIONS:
                raise ValueError(f"unsupported aggregation: {metric.aggregation}")
            for spec in metric.filters:
                if spec.op not in self.ALLOWED_FILTERS:
                    raise ValueError(f"unsupported filter operator: {spec.op}")
            for dependency in self.dependencies(key):
                if dependency not in self.metrics:
                    raise ValueError(f"unknown metric dependency: {dependency}")
                visit(dependency)
            visiting.remove(key)
            visited.add(key)

        for metric_key in self.metrics:
            visit(metric_key)

    def get(self, key: str) -> MetricDefinition:
        if key not in self.metrics:
            raise KeyError(f"unknown metric: {key}")
        return self.metrics[key]

    def required_fields(self, key: str) -> Set[str]:
        metric = self.get(key)
        fields = set(metric.required_fields)
        for dependency in self.dependencies(key):
            fields.update(self.required_fields(dependency))
        return fields

    @staticmethod
    def _apply_filters(frame: pd.DataFrame, specs: Iterable[Any]) -> pd.DataFrame:
        result = frame
        for spec in specs:
            if spec.field not in result.columns:
                if spec.field == "order_status":
                    continue
                raise ValueError(f"filter field missing: {spec.field}")
            series = result[spec.field]
            if spec.op == "eq":
                mask = series == spec.value
            elif spec.op == "ne":
                mask = series != spec.value
            elif spec.op == "in":
                mask = series.astype(str).str.lower().isin({str(value).lower() for value in spec.value})
            elif spec.op == "not_in":
                mask = ~series.astype(str).str.lower().isin({str(value).lower() for value in spec.value})
            elif spec.op == "gt":
                mask = pd.to_numeric(series, errors="coerce") > spec.value
            elif spec.op == "gte":
                mask = pd.to_numeric(series, errors="coerce") >= spec.value
            elif spec.op == "lt":
                mask = pd.to_numeric(series, errors="coerce") < spec.value
            elif spec.op == "lte":
                mask = pd.to_numeric(series, errors="coerce") <= spec.value
            else:
                raise ValueError(f"unsupported filter operator: {spec.op}")
            result = result[mask]
        return result

    def compute(self, frame: pd.DataFrame, key: str) -> Any:
        metric = self.get(key)
        missing = self.required_fields(key) - set(frame.columns)
        if missing:
            raise ValueError(f"metric {key} missing fields: {sorted(missing)}")
        if metric.expression:
            values = {dep: self.compute(frame, dep) for dep in self.dependencies(key)}
            if any(value is None for value in values.values()):
                return None
            try:
                return eval(compile(ast.parse(metric.expression, mode="eval"), "<metric>", "eval"), {"__builtins__": {}}, values)
            except ZeroDivisionError:
                return None
        filtered = self._apply_filters(frame, metric.filters)
        series = filtered[metric.measure]
        if metric.aggregation == "sum":
            return float(pd.to_numeric(series, errors="coerce").sum())
        if metric.aggregation == "count":
            return int(series.count())
        if metric.aggregation == "count_distinct":
            return int(series.nunique(dropna=True))
        if metric.aggregation == "mean":
            return float(pd.to_numeric(series, errors="coerce").mean())
        if metric.aggregation == "min":
            return series.min()
        if metric.aggregation == "max":
            return series.max()
        raise ValueError(f"unsupported aggregation: {metric.aggregation}")

    def compute_many(self, frame: pd.DataFrame, keys: Iterable[str]) -> Dict[str, Any]:
        return {key: self.compute(frame, key) for key in keys}
