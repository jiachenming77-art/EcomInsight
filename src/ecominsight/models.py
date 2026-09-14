from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class RunStatus(str, Enum):
    created = "created"
    validated = "validated"
    running = "running"
    completed = "completed"
    failed = "failed"
    blocked = "blocked"


class FieldMapping(BaseModel):
    semantic: str
    source: str
    confidence: float = Field(ge=0, le=1)
    reason: str
    confirmed: bool = False


class SemanticContract(BaseModel):
    mappings: List[FieldMapping]
    timezone: str = "Asia/Shanghai"
    assumptions: List[str] = Field(default_factory=list)

    def source_for(self, semantic: str) -> Optional[str]:
        for mapping in self.mappings:
            if mapping.semantic == semantic and mapping.confirmed:
                return mapping.source
        return None


class FilterSpec(BaseModel):
    field: str
    op: str
    value: Any


class MetricDefinition(BaseModel):
    key: str
    label: str
    description: str = ""
    entity: str = "row"
    measure: Optional[str] = None
    aggregation: Optional[str] = None
    expression: Optional[str] = None
    filters: List[FilterSpec] = Field(default_factory=list)
    unit: str = "number"
    required_fields: List[str] = Field(default_factory=list)
    version: int = 1
    zero_division: Optional[str] = "null"

    @model_validator(mode="after")
    def validate_formula(self) -> MetricDefinition:
        base = self.measure is not None and self.aggregation is not None
        if base == (self.expression is not None):
            raise ValueError("metric must define either measure+aggregation or expression")
        return self


class ComparisonWindow(BaseModel):
    current: List[str]
    baseline: List[str]
    timezone: str = "Asia/Shanghai"

    @model_validator(mode="after")
    def validate_ranges(self) -> ComparisonWindow:
        if len(self.current) != 2 or len(self.baseline) != 2:
            raise ValueError("current and baseline must each contain start and end")
        if self.current[0] > self.current[1] or self.baseline[0] > self.baseline[1]:
            raise ValueError("comparison ranges must be ordered")
        return self


class PlanStep(BaseModel):
    id: str
    op: str
    metric: Optional[str] = None
    tree: Optional[str] = None
    dimensions: List[str] = Field(default_factory=list)
    top_n: int = Field(default=10, ge=1, le=50)


class AnalysisPlan(BaseModel):
    question: str
    objective: str
    target_metric: str
    comparison: Optional[ComparisonWindow] = None
    steps: List[PlanStep]
    assumptions: List[str] = Field(default_factory=list)
    required_fields: List[str] = Field(default_factory=list)
    confirmation_required: bool = False
    confirmation_reason: Optional[str] = None


class Evidence(BaseModel):
    evidence_id: str
    run_id: str
    step_id: str
    metric_key: str
    metric_version: int = 1
    label: str
    value: Any
    unit: str
    source: Dict[str, Any]
    filters: List[Dict[str, Any]] = Field(default_factory=list)
    formula: str
    grain: str = "all"
    sample_size: int = 0
    engine: str = "pandas"
    limitations: List[str] = Field(default_factory=list)


class Claim(BaseModel):
    claim_id: str
    text: str
    level: str
    evidence_ids: List[str]
    limitations: List[str] = Field(default_factory=list)
    identification_strategy: Optional[str] = None


class RunManifest(BaseModel):
    run_id: str
    status: RunStatus
    created_at: datetime
    dataset_hash: str
    semantic_contract_hash: str
    metric_config_hash: str
    analysis_plan_hash: str
    code_version: str
    python_version: str
    engine: str = "pandas"
    random_seed: int = 42
    timezone: str = "Asia/Shanghai"
    warnings: List[str] = Field(default_factory=list)
