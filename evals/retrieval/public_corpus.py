"""Convert TechManualQA-700 and TechQA-RAG-Eval into passages and qrels.

Splits are functions of published ids and labels. They do not read retrieval scores.
"""

import hashlib
import json
import re
import zipfile
from pathlib import Path

SOURCE = json.loads((Path(__file__).resolve().parent / "public_source.json").read_text(encoding="utf-8"))
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+")


def file_sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def index_tokens(text):
    """Same tokenizer as search_manual, without the 80-term demo cap.

    Queries still go through search_tokens, which keeps that cap. Public
    documents keep every term so a code past the first 80 terms remains indexed.
    """
    tokens = []
    for word in TOKEN_RE.findall(text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            tokens.extend(word[i:i + 2] for i in range(len(word) - 1))
        else:
            tokens.append(word)
    return list(dict.fromkeys(tokens))


def _question_key(question_id):
    prefix, number = question_id.rsplit("_Q", 1)
    return prefix, int(number)


def assign_techmanualqa_split(rows):
    """Even/odd within each category. Even indexes are dev."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append(row)
    splits = {}
    for category in sorted(grouped):
        ordered = sorted(grouped[category], key=lambda item: _question_key(item["question_id"]))
        for index, row in enumerate(ordered):
            splits[row["question_id"]] = "dev" if index % 2 == 0 else "test"
    return splits


def techqa_split(question_id):
    if question_id.startswith("DEV_"):
        return "dev"
    if question_id.startswith("TRAIN_"):
        return "test"
    raise ValueError("techqa id has no official split prefix: " + question_id)


def _passage(passage_id, title, body):
    return {"id": passage_id, "title": title, "body": body, "device_type": "benchmark"}


def convert_techmanualqa(rows):
    splits = assign_techmanualqa_split(rows)
    passages = {}
    queries = []
    for row in rows:
        category = row["category"]
        unanswerable = category == "Unanswerable" or str(row.get("gt_page_number")) == "None"
        snippet = (row.get("gt_answer_snippet") or "").strip()
        relevant = []
        if not unanswerable:
            if not snippet or snippet == "Not Answered":
                raise ValueError("answerable row has no snippet: " + row["question_id"])
            raw = row["doc_id"] + "\n" + snippet
            passage_id = "tmq-" + hashlib.sha256(raw.encode()).hexdigest()[:16]
            passages.setdefault(passage_id, _passage(passage_id, row["doc_id"], snippet))
            relevant = [passage_id]
        queries.append({
            "id": row["question_id"],
            "split": splits[row["question_id"]],
            "query": row["question_text"],
            "relevant_ids": relevant,
            "kind": "unanswerable" if unanswerable else category,
            "language": row.get("language") or "en",
            "answerable": not unanswerable,
            "doc_id": row["doc_id"],
        })
    queries.sort(key=lambda item: item["id"])
    ordered = [passages[key] for key in sorted(passages)]
    return ordered, queries


def convert_techqa(rows, files):
    """files maps filename to document text."""
    missing = []
    passages = {}
    queries = []
    for name, text in files.items():
        passages[name] = _passage(name, name, text)
    for row in rows:
        split = techqa_split(row["id"])
        contexts = row.get("contexts") or []
        if row["is_impossible"]:
            if contexts:
                raise ValueError("impossible question has contexts: " + row["id"])
            relevant = []
        else:
            if len(contexts) != 1:
                raise ValueError("expected one gold context: " + row["id"])
            name = contexts[0]["filename"]
            if name not in passages:
                missing.append(name)
                continue
            relevant = [name]
        queries.append({
            "id": row["id"],
            "split": split,
            "query": row["question"],
            "relevant_ids": relevant,
            "kind": "unanswerable" if row["is_impossible"] else "answerable",
            "language": "en",
            "answerable": not row["is_impossible"],
        })
    if missing:
        raise ValueError("gold files missing from corpus: " + ",".join(sorted(set(missing))[:5]))
    queries.sort(key=lambda item: item["id"])
    return [passages[key] for key in sorted(passages)], queries


def load_techqa_files(path: Path):
    path = Path(path)
    files = {}
    if path.is_dir():
        for item in sorted(path.glob("*.txt")):
            files[item.name] = item.read_text(encoding="utf-8")
        return files
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.filename.endswith(".txt"):
                    name = info.filename.rsplit("/", 1)[-1]
                    files[name] = archive.read(info).decode("utf-8")
        return files
    raise ValueError("techqa corpus must be a directory or zip")


def load_fixture(dataset):
    if dataset == "techmanualqa":
        rows = [json.loads(line) for line in (FIXTURES / "techmanualqa_mini.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        return convert_techmanualqa(rows)
    if dataset == "techqa":
        rows = json.loads((FIXTURES / "techqa_mini.json").read_text(encoding="utf-8"))
        files = load_techqa_files(FIXTURES / "techqa_mini_corpus")
        return convert_techqa(rows, files)
    raise ValueError("unknown dataset")


def load_official(dataset, questions: Path, corpus: Path | None = None):
    spec = SOURCE[dataset]
    questions = Path(questions)
    digest = file_sha256(questions)
    if dataset == "techmanualqa":
        if digest != spec["jsonl_sha256"]:
            raise SystemExit("TechManualQA 文件哈希与 public_source.json 不一致，未评测。")
        rows = [json.loads(line) for line in questions.read_text(encoding="utf-8").splitlines() if line.strip()]
        return convert_techmanualqa(rows)
    if digest != spec["train_json_sha256"]:
        raise SystemExit("TechQA train.json 哈希与 public_source.json 不一致，未评测。")
    if corpus is None:
        raise SystemExit("TechQA 需要语料 zip 或目录。")
    corpus = Path(corpus)
    if corpus.is_file() and file_sha256(corpus) != spec["corpus_zip_sha256"]:
        raise SystemExit("TechQA corpus.zip 哈希与 public_source.json 不一致，未评测。")
    rows = json.loads(questions.read_text(encoding="utf-8"))
    return convert_techqa(rows, load_techqa_files(corpus))


def select_split(queries, split):
    chosen = [item for item in queries if item["split"] == split]
    if not chosen:
        raise SystemExit("切分里没有查询：" + split)
    return chosen

