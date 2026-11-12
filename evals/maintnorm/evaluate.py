"""Score MaintNorm splits. The default method is the rule baseline and makes no API call."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from evals.common import file_sha256, run_record
from evals.maintnorm.metrics import combine, parse_norm, score_tokens
from react_agent.normalise import apply_rules, llm_record, prompt_document, prompt_sha256, rules_sha256
from react_agent.store import content_hash

ROOT = Path(__file__).resolve().parents[2]
SOURCE = json.loads((Path(__file__).resolve().parent / "SOURCE.json").read_text(encoding="utf-8"))


def most_frequent(train_sentences):
    counts = defaultdict(Counter)
    for sentence in train_sentences:
        for raw, gold in sentence:
            counts[raw][gold] += 1
    table = {}
    for raw, counter in counts.items():
        # Tie break is documented: highest count, then shortest replacement, then code point order.
        table[raw] = sorted(counter.items(), key=lambda item: (-item[1], len(item[0]), item[0]))[0][0]
    return table


def predict_sentence(method, sentence, table, model):
    raws = [raw for raw, _gold in sentence]
    if method == "lai":
        return raws, None
    if method == "rules":
        return [apply_rules(raw) for raw in raws], None
    if method == "mfr":
        return [table.get(raw, raw) for raw in raws], None
    if method == "scripted":
        return [gold for _raw, gold in sentence], None
    try:
        record = llm_record(model, " ".join(raws))
    except Exception as exc:
        return raws, type(exc).__name__
    return [pair["norm"] for pair in record["pairs"]], None


def score_split(sentences, method, table, model):
    counted = []
    errors = Counter()
    for sentence in sentences:
        predicted, error = predict_sentence(method, sentence, table, model)
        if error:
            errors[error] += 1
        counted.append(score_tokens((raw, gold, pred) for (raw, gold), pred in zip(sentence, predicted, strict=True)))
    metrics = combine(counted)
    metrics["sentence_count"] = len(sentences)
    metrics["call_errors"] = dict(errors)
    metrics["failed_calls_scored_as_unchanged"] = sum(errors.values())
    return metrics


def assert_prompt_policy(split, sentences):
    document, _raw = prompt_document()
    if split == "test" and not (document.get("frozen") and document.get("frozen_before_split") == "test"):
        raise SystemExit("测试集要求提示词已冻结。当前 normalise_prompt.json 未标记 frozen_before_split=test。")
    banned = {" ".join(example["tokens"]) for example in document["examples"]}
    for sentence in sentences:
        text = " ".join(raw for raw, _gold in sentence)
        if text in banned:
            raise SystemExit("few-shot 例句出现在待评分切分中，已停止。")
    return document


def load_split(root: Path, subset: str, split: str, fixture: bool):
    path = root / f"{split}.norm" if fixture else root / subset / f"{split}.norm"
    if not path.is_file():
        raise SystemExit(f"找不到切分文件 {path}。先运行 evals/maintnorm/fetch.py，或使用 --fixture。")
    return path, parse_norm(path.read_text(encoding="utf-8"))


def evaluate(root, *, subset, split, method, fixture, model, seed, limit):
    if method == "scripted" and not fixture:
        raise SystemExit("scripted 只用于内置小样例，不能给官方测试集写分数。")
    if split == "dev":
        split = "val"
    path, sentences = load_split(root, subset, split, fixture)
    if limit:
        sentences = sentences[:limit]
    document = assert_prompt_policy(split, sentences)
    table = {}
    if method == "mfr":
        _train_path, train = load_split(root, subset, "train", fixture)
        table = most_frequent(train)
    metrics = score_split(sentences, method, table, model)
    if method == "llm":
        prompt_version = document["version"]
        digest = prompt_sha256()
        model_id = model.settings.model
    elif method == "scripted":
        prompt_version, digest, model_id = "scripted-oracle", content_hash("scripted-oracle"), "scripted_oracle"
    elif method == "rules":
        prompt_version, digest, model_id = "maintnorm-rules-v1", rules_sha256(), "rules"
    else:
        prompt_version, digest, model_id = method + "-v1", content_hash({"method": method}), method
    dataset = {"name": "MaintNorm" if not fixture else "maintnorm-mini-fixture",
               "revision": SOURCE["github_commit"], "license": SOURCE["license"],
               "subset": subset, "split": split, "language": "en",
               "file_sha256": file_sha256(path), "sentence_count": len(sentences),
               "fixture": fixture}
    return run_record(
        root=ROOT, model_id=model_id, prompt_version=prompt_version, prompt_sha256=digest,
        dataset=dataset, seed=seed, split=split,
        extra={"metrics": metrics, "method": method,
               "note": "Token alignment comes from the .norm lines. This is not a ByT5 decoding run. "
                       "Paper baselines stay in BASELINES.md and are not copied into metrics."},
    )


def main():
    parser = argparse.ArgumentParser(description="评测 MaintNorm 英文官方切分")
    parser.add_argument("--data", type=Path, help="fetch.py 下载目录")
    parser.add_argument("--fixture", type=Path, help="含 train.norm/val.norm/test.norm 的小样例目录")
    parser.add_argument("--subset", default="combined", choices=["combined", "company_a", "company_b", "company_c"])
    parser.add_argument("--split", default="test", choices=["train", "val", "dev", "test"])
    parser.add_argument("--method", default="rules", choices=["lai", "rules", "mfr", "llm", "scripted"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.data) == bool(args.fixture):
        raise SystemExit("请在 --data 和 --fixture 中选择一个。")
    model = None
    if args.method == "llm":
        from react_agent.config import Settings
        from react_agent.llm import DeepSeekModel
        from react_agent.models import MissingModelConfig
        settings = Settings.from_env()
        if not settings.api_key:
            raise SystemExit("DEEPSEEK_API_KEY 未配置，未写入结果。")
        try:
            model = DeepSeekModel(settings)
        except MissingModelConfig:
            raise SystemExit("DEEPSEEK_API_KEY 未配置，未写入结果。") from None
    record = evaluate(args.fixture or args.data, subset=args.subset, split=args.split, method=args.method,
                      fixture=args.fixture is not None, model=model, seed=args.seed, limit=args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
