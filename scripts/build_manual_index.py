"""Build the sqlite-vec manual index. BM25 does not need this file."""

import argparse
import json
from pathlib import Path

from react_agent.config import Settings
from react_agent.retrieval import EMBEDDING_MODEL
from react_agent.store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线构建手册向量索引")
    parser.add_argument("--db", type=Path, default=Path("runtime/business.db"))
    parser.add_argument("--fixture", type=Path, action="append", default=[],
                        help="标明为 adapted_synthetic_demo 的 JSON，可重复")
    parser.add_argument("--embedder", choices=["fake", "sentence-transformers"], default="sentence-transformers")
    parser.add_argument("--model", default=EMBEDDING_MODEL)
    args = parser.parse_args(argv)
    store = Store(args.db)
    for fixture in args.fixture:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        store.import_fixture(payload)
    settings = Settings(data_dir=args.db.parent, retriever="dense", embedder=args.embedder,
                        embedding_model=args.model)
    from react_agent.retrieval import ManualRetriever
    try:
        meta = ManualRetriever(settings, store).build_index()
    except Exception as exc:
        code = str(exc) or type(exc).__name__
        raise SystemExit(f"索引未写入：{code}") from None
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
