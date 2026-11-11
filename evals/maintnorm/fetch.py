"""Download the official MaintNorm splits. The corpus is not committed."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

REVISION = "e98ca406f7afffbb0ab3243aa7c922f3b64bc7c8"
SUBSETS = ("combined", "company_a", "company_b", "company_c")
SPLITS = ("train", "val", "test")


def main():
    parser = argparse.ArgumentParser(description="下载 MaintNorm 官方 train/val/test")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--direct", action="store_true")
    args = parser.parse_args()
    opener = build_opener(ProxyHandler({})) if args.direct else build_opener()
    manifest = {"revision": REVISION, "license": "MIT",
                "repository": "https://github.com/nlp-tlp/maintnorm", "files": {}}
    for subset in SUBSETS:
        for split in SPLITS:
            url = f"https://raw.githubusercontent.com/nlp-tlp/maintnorm/{REVISION}/data/{subset}/{split}.norm"
            with opener.open(url, timeout=60) as response:
                raw = response.read()
            relative = f"{subset}/{split}.norm"
            target = args.out / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            manifest["files"][relative] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "url": url}
            print(f"saved {relative}: {len(raw)} bytes")
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(args.out / "manifest.json")


if __name__ == "__main__":
    main()
