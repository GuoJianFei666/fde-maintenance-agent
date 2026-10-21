"""Inspect candidate Git files without exposing local credential values."""

import json
import os
import re
import stat
import subprocess
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=root, check=True, capture_output=True).stdout.decode().split("\0")
    ignored = subprocess.run(["git", "check-ignore", ".env"], cwd=root, capture_output=True, check=True)
    assert ignored.stdout.strip() == b".env"
    env = root / ".env"
    key = ""
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                key = line.partition("=")[2].strip()
    paths = []
    for relative in sorted(set(listed) - {""}):
        path = root / relative
        if not path.exists():
            continue  # A deleted upstream file is not part of the new tree.
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
        assert not path.is_symlink() and not (attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT), relative
        assert os.path.commonpath([str(root), str(path.resolve())]) == str(root), relative
        assert not relative.startswith((".env", ".venv/", "runtime/")) or relative == ".env.example", relative
        raw = path.read_bytes()
        assert not key or key.encode() not in raw, "Local credential found in " + relative
        assert not re.search(rb"sk-[A-Za-z0-9_-]{24,}", raw), "Credential-like value found in " + relative
        paths.append(relative)
    print(json.dumps({"status": "pass", "candidate_file_count": len(paths), "credential_matches": 0,
                      "env_ignored": True, "runtime_and_venv_excluded": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
