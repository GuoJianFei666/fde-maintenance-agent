"""Download pinned AssetOpsBench sample files. The default check uses no network.

The full Chiller 6 series and the other IoT files are written under the chosen
output directory, which should stay gitignored. PHMForge signal archives are
not downloaded. The 99 scenario rows are optional and are not imported.
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from evals.assetopsbench.official_sample import COMMIT, MANIFEST, verify_committed_files

ROOT = "https://raw.githubusercontent.com/IBM/AssetOpsBench/" + COMMIT + "/"
PHM = MANIFEST["phmforge"]


def _open(url, direct):
    opener = build_opener(ProxyHandler({})) if direct else build_opener()
    with opener.open(url, timeout=180) as response:
        return response.read()


def _save(raw, dest: Path, spec):
    digest = hashlib.sha256(raw).hexdigest()
    if digest != spec["sha256"] or len(raw) != spec["bytes"]:
        raise SystemExit(f"{dest.name} 的哈希或大小与清单不一致，未保存。")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    print(dest)


def main():
    parser = argparse.ArgumentParser(description="校验或下载 AssetOpsBench 官方样本")
    parser.add_argument("--out", type=Path, help="下载目录。校验已提交文件时可以不填。")
    parser.add_argument("--check", action="store_true", help="只校验仓库里的小文件，不访问网络。")
    parser.add_argument("--chiller", action="store_true", help="下载 chiller_6.json。")
    parser.add_argument("--all-iot", action="store_true", help="另下载液压泵、地铁泵和电机样本。")
    parser.add_argument("--phmforge-scenarios", action="store_true", help="只下载 PHMForge 的 99 条场景，不含信号。")
    parser.add_argument("--direct", action="store_true", help="本次下载绕过系统代理。")
    args = parser.parse_args()
    verified = verify_committed_files()
    print(f"checked {len(verified)} committed official files")
    downloads = args.chiller or args.all_iot or args.phmforge_scenarios
    if not downloads:
        return
    if args.out is None:
        raise SystemExit("下载时必须给出 --out。不要写进 fixtures/official。")
    if args.chiller or args.all_iot:
        _save(_open(ROOT + MANIFEST["chiller_6"]["upstream_path"], args.direct),
              args.out / "chiller_6.json", MANIFEST["chiller_6"])
    if args.all_iot:
        for spec in MANIFEST["not_imported_iot"].values():
            if not isinstance(spec, dict):
                continue
            name = Path(spec["upstream_path"]).name
            _save(_open(ROOT + spec["upstream_path"], args.direct), args.out / name, spec)
    if args.phmforge_scenarios:
        url = ("https://huggingface.co/datasets/ibm-research/PHMForge/resolve/"
               f"{PHM['revision']}/{PHM['scenarios_file']}")
        spec = {"sha256": PHM["scenarios_sha256"], "bytes": PHM["scenarios_bytes"]}
        _save(_open(url, args.direct), args.out / "phmforge_all.jsonl", spec)
        rows = [json.loads(line) for line in (args.out / "phmforge_all.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        if len(rows) != PHM["scenario_count"]:
            raise SystemExit("PHMForge 场景条数与清单不一致。")
        print("phmforge scenarios", len(rows), "not imported")


if __name__ == "__main__":
    main()
