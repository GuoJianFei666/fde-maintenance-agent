"""Turn selected AssetOpsBench utterances into this repository's eval cases."""

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE = Path(__file__).resolve().parent / "fixtures" / "upstream_sample.jsonl"
DEFAULT_ADAPTATIONS = Path(__file__).resolve().parent / "adaptations.json"
DEFAULT_SOURCE = Path(__file__).resolve().parent / "SOURCE.json"

CASE_FIELDS = (
    "id", "upstream_id", "upstream_text", "message", "device_id", "severity", "expected_status",
    "required_tools", "optional_tools", "forbidden_tools", "order", "expected_evidence",
    "forbidden_behaviors", "unsafe_write_probe", "manual_query", "summary", "adaptation",
    "data_gap", "upstream_type", "upstream_category", "upstream_characteristic_form",
    "source_revision", "github_commit", "license",
)


def load_jsonl(path: Path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def convert(utterances, adaptations, source):
    by_id = {row["id"]: row for row in utterances}
    cases = []
    for key, spec in adaptations["cases"].items():
        upstream_id = int(key)
        if upstream_id not in by_id:
            raise KeyError(f"selected utterance {upstream_id} is not in the input file")
        row = by_id[upstream_id]
        message = row["text"].strip()
        cases.append(_case(f"aob-{upstream_id}", upstream_id, row, message, spec, source, "adapted_to_local_tools"))
    for probe in adaptations.get("probes", []):
        row = by_id[probe["based_on"]]
        base = adaptations["cases"][str(probe["based_on"])]
        spec = dict(base)
        spec["forbidden_behaviors"] = [*base["forbidden_behaviors"], *probe.get("extra_forbidden_behaviors", [])]
        spec["unsafe_write_probe"] = True
        message = row["text"].strip() + probe["suffix"]
        cases.append(_case(probe["id"], probe["based_on"], row, message, spec, source, probe["adaptation"]))
    return cases


def _case(case_id, upstream_id, row, message, spec, source, adaptation):
    if spec["expected_status"] not in {"awaiting_approval", "needs_information"}:
        raise ValueError("unexpected status")
    if spec["expected_status"] == "awaiting_approval" and not spec.get("expected_evidence"):
        raise ValueError("draft case needs expected evidence")
    return {
        "id": case_id,
        "upstream_id": upstream_id,
        "upstream_text": row["text"],
        "message": message,
        "device_id": spec["device_id"],
        "severity": spec.get("severity", "warning"),
        "expected_status": spec["expected_status"],
        "required_tools": spec["required_tools"],
        "optional_tools": spec.get("optional_tools", []),
        "forbidden_tools": spec.get("forbidden_tools", []),
        "order": spec["order"],
        "expected_evidence": spec["expected_evidence"],
        "forbidden_behaviors": spec["forbidden_behaviors"],
        "unsafe_write_probe": bool(spec.get("unsafe_write_probe", False)),
        "manual_query": spec.get("manual_query"),
        "summary": spec.get("summary"),
        "adaptation": adaptation,
        "data_gap": spec["data_gap"],
        "upstream_type": row.get("type"),
        "upstream_category": row.get("category"),
        "upstream_characteristic_form": row.get("characteristic_form"),
        "source_dataset": source["dataset"],
        "source_revision": source["dataset_revision"],
        "github_commit": source["github_commit"],
        "license": source["license"],
    }


def write_cases(cases, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8")
    yaml_path = path.with_suffix(".yaml")
    yaml_path.write_text(yaml.safe_dump({"cases": cases}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return yaml_path


def main():
    parser = argparse.ArgumentParser(description="转换 AssetOpsBench 子集为本地告警评测用例")
    parser.add_argument("--utterances", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--adaptations", type=Path, default=DEFAULT_ADAPTATIONS)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=ROOT / "evals" / "assetopsbench" / "cases" / "alarm_subset.jsonl")
    args = parser.parse_args()
    cases = convert(load_jsonl(args.utterances), json.loads(args.adaptations.read_text(encoding="utf-8")),
                    json.loads(args.source.read_text(encoding="utf-8")))
    missing = [name for name in CASE_FIELDS if any(name not in case for case in cases)]
    if missing:
        raise SystemExit("missing fields: " + ",".join(missing))
    yaml_path = write_cases(cases, args.out)
    print(f"wrote {len(cases)} cases to {args.out} and {yaml_path}")


if __name__ == "__main__":
    main()
