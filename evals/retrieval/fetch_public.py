"""Download TechManualQA-700 or TechQA-RAG-Eval and check the pinned hashes."""

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from evals.retrieval.public_corpus import SOURCE, file_sha256

URLS = {
    "techmanualqa": "https://zenodo.org/records/17410809/files/TechManualQA_700.zip?download=1",
    "techqa_json": "https://huggingface.co/datasets/nvidia/TechQA-RAG-Eval/resolve/main/train.json",
    "techqa_corpus": "https://huggingface.co/datasets/nvidia/TechQA-RAG-Eval/resolve/main/corpus.zip",
}


def _get(url, direct):
    opener = build_opener(ProxyHandler({})) if direct else build_opener()
    with opener.open(url, timeout=120) as response:
        return response.read()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fetch_techmanualqa(out: Path, direct):
    spec = SOURCE["techmanualqa"]
    raw = _get(URLS["techmanualqa"], direct)
    digest = hashlib.md5(raw).hexdigest()
    if digest != spec["zip_md5"]:
        raise SystemExit("TechManualQA zip MD5 与记录不一致，未保存。")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        name = next(item for item in archive.namelist() if item.endswith("TechManualQA_700.jsonl"))
        payload = archive.read(name)
    if _sha(payload) != spec["jsonl_sha256"] or len(payload) != spec["jsonl_bytes"]:
        raise SystemExit("TechManualQA jsonl 哈希或大小与记录不一致，未保存。")
    out.mkdir(parents=True, exist_ok=True)
    target = out / "TechManualQA_700.jsonl"
    target.write_bytes(payload)
    return target


def fetch_techqa(out: Path, direct):
    spec = SOURCE["techqa"]
    payload = _get(URLS["techqa_json"], direct)
    corpus = _get(URLS["techqa_corpus"], direct)
    if _sha(payload) != spec["train_json_sha256"] or len(payload) != spec["train_json_bytes"]:
        raise SystemExit("TechQA train.json 哈希或大小与记录不一致，未保存。")
    if _sha(corpus) != spec["corpus_zip_sha256"] or len(corpus) != spec["corpus_zip_bytes"]:
        raise SystemExit("TechQA corpus.zip 哈希或大小与记录不一致，未保存。")
    out.mkdir(parents=True, exist_ok=True)
    questions = out / "train.json"
    archive = out / "corpus.zip"
    questions.write_bytes(payload)
    archive.write_bytes(corpus)
    return questions


def main():
    parser = argparse.ArgumentParser(description="下载公开检索评测集并校验哈希")
    parser.add_argument("--dataset", choices=["techmanualqa", "techqa"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--direct", action="store_true")
    args = parser.parse_args()
    if args.dataset == "techmanualqa":
        target = fetch_techmanualqa(args.out, args.direct)
    else:
        target = fetch_techqa(args.out, args.direct)
    manifest = {"dataset": args.dataset, "sha256": file_sha256(target), "path": str(target)}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
