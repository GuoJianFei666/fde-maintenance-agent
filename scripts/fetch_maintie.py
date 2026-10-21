"""Re-download the fixed public release; verify all bytes before writing files."""

import argparse
import hashlib
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from react_agent.maintie import load_corpus


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--direct", action="store_true", help="Bypass local proxy for these downloads only")
    args = parser.parse_args()
    manifest, _ = load_corpus()
    opener = build_opener(ProxyHandler({})) if args.direct else build_opener()
    downloads = {}
    for name, expected in manifest["files"].items():
        remote = "data/gold_release.json" if name == "gold_release.json" else name.replace(".upstream", "")
        url = f"https://raw.githubusercontent.com/nlp-tlp/maintie/{manifest['revision']}/{remote}"
        with opener.open(url, timeout=30) as response:
            raw = response.read(2_000_001)
        if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
            raise ValueError("maintie_download_hash_mismatch:" + name)
        downloads[name] = raw
    args.out.mkdir(parents=True, exist_ok=True)
    for name, raw in downloads.items():
        target = args.out / name
        if target.exists() and target.read_bytes() != raw:
            raise FileExistsError(str(target))
        target.write_bytes(raw)
        print(f"verified {name}: {len(raw)} bytes")


if __name__ == "__main__":
    main()
