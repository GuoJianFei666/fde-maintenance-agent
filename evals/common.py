"""Shared run metadata. A results file records what was actually executed."""

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def git_commit(root: Path):
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def file_sha256(path: Path):
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_record(*, root: Path, model_id: str, prompt_version: str, prompt_sha256: str, dataset: dict,
               seed: int, split: str, extra: dict | None = None):
    record = {
        "git_commit": git_commit(root),
        "model_id": model_id,
        "prompt_version": prompt_version,
        "prompt_sha256": prompt_sha256,
        "dataset": dataset,
        "seed": seed,
        "split": split,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scores_are_model_results": model_id not in {"scripted_test", "scripted_oracle", "rules", "mfr", "lai"},
    }
    if extra:
        record.update(extra)
    return record
