"""Lexical normalisation and masking before maintenance-text extraction.

The rule table is a small baseline. The few-shot prompt is authored for this
project and is frozen before the MaintNorm test split is scored.
"""

import json
import re
from importlib.resources import files

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from react_agent.models import ModelCallError
from react_agent.store import canonical_json, content_hash

RULES_VERSION = "maintnorm-rules-v1"
_WS = re.compile(r"\s+")
_DATE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})$")
_NUMBER = re.compile(r"^\d+$")
_ASSET = re.compile(r"^[A-Za-z]{1,4}\d{2,6}$")
ABBREVIATIONS = {
    "&": "and",
    "a/c": "air conditioner",
    "c/o": "change out",
    "eng": "engine",
    "hyd": "hydraulic",
    "insp": "inspection",
    "p/brake": "park brake",
    "pos": "position",
    "r/h": "right hand",
    "l/h": "left hand",
    "repl": "replace",
    "u/s": "unserviceable",
    "w/shop": "workshop",
}
COMMON_LOWER = {
    "air", "and", "belt", "brake", "bucket", "clamps", "compressor", "conditioner", "cut",
    "damage", "damaged", "engine", "exhaust", "fault", "filter", "glass", "hand", "hose",
    "hour", "hydraulic", "inspection", "items", "leak", "left", "linear", "locks", "mechanical",
    "next", "number", "oil", "park", "pins", "position", "pressure", "pump", "received",
    "remount", "repair", "replace", "reshim", "right", "roller", "scheduled", "sensor",
    "servicing", "steering", "supply", "switches", "turbo", "tyre", "unserviceable",
    "wheelend", "window", "workshop",
}


def prompt_document():
    raw = files("react_agent").joinpath("data/normalise_prompt.json").read_text(encoding="utf-8")
    return json.loads(raw), raw


def prompt_sha256():
    _document, raw = prompt_document()
    return content_hash(raw)


def rules_sha256():
    return content_hash({"version": RULES_VERSION, "abbreviations": ABBREVIATIONS,
                         "common_lower": sorted(COMMON_LOWER)})


def whitespace_tokens(text):
    return [token for token in _WS.split(text.strip()) if token]


def apply_rules(token):
    key = token.casefold()
    if key in ABBREVIATIONS:
        return ABBREVIATIONS[key]
    if _DATE.fullmatch(token):
        return "<date>"
    if _NUMBER.fullmatch(token):
        return "<num>"
    if _ASSET.fullmatch(token):
        return "<id>"
    if token.isalpha() and token.isupper() and token.lower() in COMMON_LOWER:
        return token.lower()
    return token


def rule_pairs(text):
    return [{"raw": token, "norm": apply_rules(token)} for token in whitespace_tokens(text)]


def render_pairs(pairs):
    parts = []
    for pair in pairs:
        if pair["norm"]:
            parts.extend(pair["norm"].split(" "))
    return " ".join(parts)


def rule_record(text):
    pairs = rule_pairs(text)
    rendered = render_pairs(pairs)
    return {"mode": "rules", "text": rendered, "changed": rendered != text, "pairs": pairs,
            "prompt_version": RULES_VERSION, "prompt_sha256": rules_sha256()}


class TokenNorm(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    raw: str = Field(min_length=1, max_length=80)
    norm: str = Field(max_length=160)


class Normalisation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tokens: list[TokenNorm] = Field(min_length=1, max_length=160)


def _instruction():
    document, _raw = prompt_document()
    examples = []
    for example in document["examples"]:
        examples.append({"tokens": [{"raw": raw, "norm": norm}
                         for raw, norm in zip(example["tokens"], example["norms"], strict=True)]})
    return document["version"], document["instruction"] + "\nExamples, authored for this project:\n" + canonical_json(examples)


NORMALISE_TOOL = [{"type": "function", "function": {
    "name": "submit_normalisation",
    "description": "Return one normalisation or mask for every supplied raw token, in the same order.",
    "parameters": Normalisation.model_json_schema(),
}}]


def llm_record(model, text, *, on_response=None):
    tokens = whitespace_tokens(text)
    if not tokens or len(tokens) > 160:
        raise ModelCallError("normalisation_token_limit")
    version, instruction = _instruction()
    response = model.invoke([
        SystemMessage(content=instruction),
        HumanMessage(content=canonical_json({"tokens": tokens})),
    ], NORMALISE_TOOL)
    if not isinstance(response, AIMessage):
        raise TypeError("Model adapter must return AIMessage")
    if on_response is not None:
        on_response(response)
    if len(response.tool_calls) != 1 or response.tool_calls[0]["name"] != "submit_normalisation":
        raise ModelCallError("expected_one_submit_normalisation_call")
    try:
        parsed = Normalisation.model_validate(response.tool_calls[0]["args"])
    except ValidationError:
        raise ModelCallError("invalid_normalisation_schema") from None
    if [item.raw for item in parsed.tokens] != tokens:
        raise ModelCallError("normalisation_alignment_mismatch")
    pairs = [{"raw": item.raw, "norm": item.norm} for item in parsed.tokens]
    rendered = render_pairs(pairs)
    return {"mode": "llm", "text": rendered, "changed": rendered != text, "pairs": pairs,
            "prompt_version": version, "prompt_sha256": prompt_sha256(),
            "model_name": response.response_metadata.get("model_name"),
            "usage": response.usage_metadata, "execution_mode": model.mode}
