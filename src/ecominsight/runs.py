from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from .models import AnalysisPlan, RunManifest, RunStatus, SemanticContract


def stable_json(value: Any) -> str:
    def default(item: Any) -> Any:
        if isinstance(item, (datetime, pd.Timestamp)):
            return item.isoformat()
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        return str(item)

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=default)


def stable_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def frame_hash(frame: pd.DataFrame) -> str:
    normalised = frame.copy()
    normalised = normalised.reindex(sorted(normalised.columns), axis=1)
    payload = pd.util.hash_pandas_object(normalised, index=True).values.tobytes()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def code_version(root: Path) -> str:
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.call(["git", "diff", "--quiet"], cwd=root) != 0
        return revision + ("+dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class RunManager:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        frame: pd.DataFrame,
        contract: SemanticContract,
        metric_snapshot: Dict[str, Any],
        plan: AnalysisPlan,
        project_root: Optional[Path] = None,
    ) -> RunManifest:
        now = datetime.now(timezone.utc)
        dataset_digest = frame_hash(frame)
        suffix = dataset_digest.split(":", 1)[1][:8]
        run_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "_" + suffix
        manifest = RunManifest(
            run_id=run_id,
            status=RunStatus.created,
            created_at=now,
            dataset_hash=dataset_digest,
            semantic_contract_hash=stable_hash(contract),
            metric_config_hash=stable_hash(metric_snapshot),
            analysis_plan_hash=stable_hash(plan),
            code_version=code_version(project_root or Path.cwd()),
            python_version=platform.python_version(),
            timezone=contract.timezone,
        )
        run_dir = self.path(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "results").mkdir()
        self.write(run_id, "run.json", manifest.model_dump(mode="json"))
        self.write(run_id, "input_manifest.json", {"dataset_hash": dataset_digest, "rows": len(frame), "columns": list(frame.columns)})
        self.write(run_id, "semantic_contract.json", contract.model_dump(mode="json"))
        self.write(run_id, "metric_snapshot.json", metric_snapshot)
        self.write(run_id, "analysis_plan.json", plan.model_dump(mode="json"))
        return manifest

    def path(self, run_id: str) -> Path:
        if not run_id or Path(run_id).name != run_id:
            raise ValueError("invalid run id")
        return self.root / run_id

    def write(self, run_id: str, name: str, payload: Any) -> Path:
        target = self.path(run_id) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return target

    def update_status(self, manifest: RunManifest, status: RunStatus, warning: Optional[str] = None) -> RunManifest:
        manifest.status = status
        if warning:
            manifest.warnings.append(warning)
        self.write(manifest.run_id, "run.json", manifest.model_dump(mode="json"))
        return manifest

    def replay_check(self, run_id: str, frame: pd.DataFrame) -> Dict[str, Any]:
        run_dir = self.path(run_id)
        manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        actual = frame_hash(frame)
        return {
            "run_id": run_id,
            "expected_dataset_hash": manifest["dataset_hash"],
            "actual_dataset_hash": actual,
            "replayable": actual == manifest["dataset_hash"],
            "reason": None if actual == manifest["dataset_hash"] else "dataset_hash_mismatch",
        }
