"""Run a fixed, hash-ordered local evaluation subset against the real provider."""

import argparse
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from react_agent.config import Settings
from react_agent.evaluation import metrics
from react_agent.extraction import EXTRACTION_PROMPT, EXTRACTION_VERSION, extract_text
from react_agent.llm import DeepSeekModel
from react_agent.maintie import MaintIEIndex
from react_agent.models import ModelCallError
from react_agent.store import content_hash


class RecordedModel:
    mode = "live_deepseek"

    def __init__(self, settings):
        self.inner = DeepSeekModel(settings)
        self.response = None

    def invoke(self, messages, tools):
        self.response = self.inner.invoke(messages, tools)
        return self.response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("Choose a new output path to preserve previous observations")
    settings = replace(Settings.from_env(), timeout=90)
    index = MaintIEIndex(settings.data_dir / "maintie.db")
    available = index.evaluation_records()
    if not 1 <= args.limit <= len(available):
        raise ValueError(f"limit must be in [1,{len(available)}]")
    selected = available[:args.limit]
    model = RecordedModel(settings)
    results = []
    summary = {"kind": "live_maintie_entity_evaluation", "provider": "DeepSeek", "model": settings.model,
               "performed_at": datetime.now(timezone.utc).isoformat(), "dataset": index.metadata(),
               "prompt_version": EXTRACTION_VERSION, "prompt_sha256": content_hash(EXTRACTION_PROMPT),
               "selection": "First N unique evaluation texts sorted by normalized text SHA256; no topic filtering",
               "planned_count": len(selected), "cases": results,
               "scope": "Five top-level entity types and exact token spans; no fine-grained classes or relation extraction; not a reproduction of the MaintIE paper"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for source in selected:
        model.response = None
        actual = {"case_id": source["id"], "text": source["body"], "tokens": source["tokens"],
                  "text_sha256": source["text_sha256"], "split": source["split"],
                  "expected": source["entities"], "predicted": [], "schema_valid": False}
        try:
            output = extract_text(model, source["body"], tokens=source["tokens"])
            actual.update({"predicted": output["entities"], "schema_valid": True,
                           "elapsed_ms": output["elapsed_ms"]})
        except ModelCallError as exc:
            actual["error_code"] = str(exc)
        if model.response is not None:
            actual.update({"raw_tool_calls": model.response.tool_calls, "usage": model.response.usage_metadata,
                           "observed_model": model.response.response_metadata.get("model_name")})
        results.append(actual)
        summary.update({"completed_count": len(results), "schema_valid_count": sum(r["schema_valid"] for r in results),
                        "metrics": metrics(results), "completed": len(results) == len(selected)})
        summary["observed_usage_total_tokens"] = sum(r["usage"]["total_tokens"] for r in results if r.get("usage"))
        summary["usage_recorded_call_count"] = sum(r.get("usage") is not None for r in results)
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"completed": len(results), "planned": len(selected), "case_id": source["id"],
                          "schema_valid": actual["schema_valid"], "micro_f1_so_far": summary["metrics"]["micro"]["f1"]}), flush=True)
    if summary["schema_valid_count"] != len(selected):
        raise SystemExit("Some provider outputs failed validation; failures are included in the report")


if __name__ == "__main__":
    main()
