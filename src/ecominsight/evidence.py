from __future__ import annotations

from collections.abc import Iterable
from typing import Dict, List

from .models import Claim, Evidence

CAUSAL_WORDS = ("导致", "证明", "根因", "cause", "caused", "prove")
VALID_IDENTIFICATION = {"randomized", "ab_test", "did", "matching", "iv", "rdd", "synthetic_control"}


def verify(evidence: Iterable[Evidence], claims: Iterable[Claim], run_id: str) -> Dict[str, object]:
    evidence_map: Dict[str, Evidence] = {item.evidence_id: item for item in evidence}
    issues: List[dict] = []
    for item in evidence_map.values():
        if item.run_id != run_id:
            issues.append({"code": "cross_run_evidence", "evidence_id": item.evidence_id})
    for claim in claims:
        missing = [key for key in claim.evidence_ids if key not in evidence_map]
        if missing:
            issues.append({"code": "missing_evidence", "claim_id": claim.claim_id, "evidence_ids": missing})
        causal = any(word in claim.text.lower() for word in CAUSAL_WORDS)
        if causal and claim.identification_strategy not in VALID_IDENTIFICATION:
            issues.append({"code": "unsupported_causal_claim", "claim_id": claim.claim_id})
        if claim.level in {"driver", "candidate_explanation", "causal_claim"} and not claim.evidence_ids:
            issues.append({"code": "insufficient_evidence", "claim_id": claim.claim_id})
    return {"status": "pass" if not issues else "fail", "issues": issues, "evidence_count": len(evidence_map)}


def evidence_for_result(run_id: str, step_id: str, metric_key: str, label: str, value: object, unit: str, sample_size: int, formula: str, dataset_hash: str, sequence: int) -> Evidence:
    return Evidence(
        evidence_id=f"E-{sequence:04d}",
        run_id=run_id,
        step_id=step_id,
        metric_key=metric_key,
        label=label,
        value=value,
        unit=unit,
        source={"dataset_hash": dataset_hash},
        formula=formula,
        sample_size=sample_size,
    )
