"""Download the AssetOpsBench utterance file and check the pinned sha256."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

SOURCE = json.loads((Path(__file__).resolve().parent / "SOURCE.json").read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="下载 AssetOpsBench  utterance 文件")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--direct", action="store_true")
    args = parser.parse_args()
    url = ("https://huggingface.co/datasets/ibm-research/AssetOpsBench/resolve/"
           f"{SOURCE['dataset_revision']}/{SOURCE['dataset_file']}")
    opener = build_opener(ProxyHandler({})) if args.direct else build_opener()
    with opener.open(url, timeout=60) as response:
        raw = response.read()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE["dataset_sha256"] or len(raw) > 5_000_000:
        raise SystemExit("utterance 文件哈希或大小与 SOURCE.json 不一致，未保存。")
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "all_utterance.jsonl"
    target.write_bytes(raw)
    manifest = {"revision": SOURCE["dataset_revision"], "github_commit": SOURCE["github_commit"],
                "license": SOURCE["license"], "bytes": len(raw), "sha256": digest, "url": url}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
