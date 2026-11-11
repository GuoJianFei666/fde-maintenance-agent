"""Metadata helpers for the two public retrieval datasets."""

import json
from pathlib import Path

SOURCE = json.loads((Path(__file__).resolve().parent / "public_source.json").read_text(encoding="utf-8"))


def dataset_meta(dataset):
    spec = SOURCE[dataset]
    if dataset == "techmanualqa":
        revision = spec["zenodo_doi"] + "@" + spec["github_commit"]
    else:
        revision = spec["huggingface_revision"]
    return {**spec, "revision": revision}
