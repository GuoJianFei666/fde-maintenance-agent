"""Read-only inspection for maintie; only this project dataset is included."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import tarfile
import time
import urllib.request
import zipfile


def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def obtain(spec, cache, download):
    target = cache / spec["filename"]
    if not target.exists():
        if not download:
            raise FileNotFoundError(f"Missing {target}; use --download to retrieve public data")
        print(f"Downloading {spec['id']}", flush=True)
        request = urllib.request.Request(spec["url"], headers={"User-Agent": "project-public-data/1.0"})
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=20) as response:
            chunks = []
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                if time.monotonic() - started > 180:
                    raise TimeoutError(f"Total download time exceeds 180 seconds: {spec['id']}")
            body = b"".join(chunks)
        expected = spec.get("sha256")
        actual = hashlib.sha256(body).hexdigest()
        if expected and actual != expected:
            raise ValueError(f"SHA256 mismatch for {spec['id']}: {actual}")
        target.write_bytes(body)
    body = target.read_bytes()
    actual = hashlib.sha256(body).hexdigest()
    if spec.get("sha256") and spec["sha256"] != actual:
        raise ValueError(f"Cached SHA256 mismatch: {spec['id']}")
    git_sha = hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()
    if spec.get("github_blob_sha") and git_sha != spec["github_blob_sha"]:
        raise ValueError(f"GitHub blob SHA mismatch: {spec['id']}")
    return {**spec, "bytes": len(body), "sha256": actual,
            "github_blob_verified": bool(spec.get("github_blob_sha"))}


def inspect_maintie(cache):
    result = {}
    normalized_sets = {}
    for split in ("gold", "silver"):
        rows = json.loads((cache / f"maintie_{split}.json").read_text(encoding="utf-8"))
        texts = Counter(" ".join(r["text"].casefold().split()) for r in rows)
        normalized_sets[split] = set(texts)
        top, leaves, rels = Counter(), Counter(), Counter()
        bad_spans, bad_relations = [], []
        for index, row in enumerate(rows):
            for e in row["entities"]:
                leaves[e["type"]] += 1
                top[e["type"].split("/")[0]] += 1
                if not (0 <= e["start"] < e["end"] <= len(row["tokens"])):
                    bad_spans.append({"row_index": index, "start": e["start"], "end": e["end"],
                                      "token_count": len(row["tokens"])})
            for relation in row["relations"]:
                rels[relation["type"]] += 1
                if not all(0 <= relation[k] < len(row["entities"]) for k in ("head", "tail")):
                    bad_relations.append(index)
        result[split] = {
            "records": len(rows), "normalized_unique_texts": len(texts),
            "duplicate_rows_beyond_first": len(rows) - len(texts),
            "duplicate_text_groups": sum(v > 1 for v in texts.values()),
            "tokens": sum(len(r["tokens"]) for r in rows),
            "entities": sum(top.values()), "observed_entity_type_count": len(leaves),
            "top_level_entities": dict(sorted(top.items())),
            "relations": sum(rels.values()), "observed_relation_types": dict(sorted(rels.items())),
            "invalid_entity_spans": bad_spans, "invalid_relation_row_indices": bad_relations,
        }
    result["normalized_gold_silver_shared_texts"] = len(normalized_sets["gold"] & normalized_sets["silver"])
    result["normalization"] = "Python str.casefold plus whitespace split/join; exact text match only"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'data/downloads.json').read_text(encoding='utf-8'))
    args.cache.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda spec: obtain(spec, args.cache, args.download), manifest['files']))
    result = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'method': 'Python standard-library read-only data inspection; not model or application evaluation',
              'maintie': inspect_maintie(args.cache)}
    dump(args.output, result)
    dump(args.output.with_name('source-files.json'), {'files': records})
    print(json.dumps({'dataset': 'maintie', 'inspected_files': len(records)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
