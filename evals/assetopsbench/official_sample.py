"""Load the pinned AssetOpsBench scenario sample into the eval store.

The full Chiller 6 series stays out of Git. The committed excerpt is the first
and last official records and is what CI loads. Scenario 3's detector flag is
not copied onto the device.
"""

import csv
import hashlib
import json
import os
import re
from pathlib import Path

from react_agent.models import NotFoundError

HERE = Path(__file__).resolve().parent
FIXTURE_DIR = HERE / "fixtures" / "official"
MANIFEST = json.loads((FIXTURE_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
COMMIT = MANIFEST["commit"]
RUNTIME_CHILLER = HERE / "runtime" / "chiller_6.json"
DEVICE_ID = re.compile(r"^[A-Z][A-Z0-9-]{1,30}$")
SOURCE_LABEL = "IBM/AssetOpsBench " + COMMIT
FLOW_SENSOR = "Chiller 6 Condenser Water Flow"
LOADED_SENSOR = "Chiller 6 Chiller % Loaded"

EVAL_IDS = {
    "Chiller 6": "CH-6",
    "mp_1": "MP-1",
    "hyd_1": "HYD-1",
    "Motor_01": "MOTOR-01",
    "PUMP3": "PUMP3",
    "AHU2": "AHU2",
}
WORK_ORDER_DEVICES = {"CHILLER6": "CH-6", "PUMP3": "PUMP3", "AHU2": "AHU2"}
TYPE_MAP = {
    "CHILLER": "chiller",
    "COMPRESSOR": "compressor",
    "HYDRAULIC_PUMP": "pump",
    "MOTOR": "motor",
    "PUMP": "pump",
    "AHU": "ahu",
}

LOOKUP = {
    1: "sites",
    2: "sites",
    3: "assets_at_main",
    4: "assets_at_main",
    5: "chiller_6_metadata",
    47: "chillers_at_main",
}
PARTIAL = {
    9: "june_2020_window_ends_26",
    12: "june_2020_window_ends_26",
    104: "sensor_list_disagrees_with_characteristic_form",
    603: "sensor_list_disagrees_with_characteristic_form",
}

LOOKUP_GAP = (
    "The official asset profile sample answers this list or metadata question. "
    "The question does not ask for a work order, so the expected status stays needs_information "
    "and draft_work_order stays forbidden."
)
JUNE_GAP = (
    "Official chiller_6.json runs from 2020-06-01T00:00:00 through 2020-06-26T11:14:36 (2896 rows). "
    "The utterance asks for 1 June 2020 through 30 June 2020 inclusive. 27-30 June are absent. "
    "Do not invent those readings and do not draft a work order."
)
SENSOR_GAP = (
    "The official asset profile lists 12 sensors, including Chiller 6 Setpoint Temperature and "
    "Chiller 6 Oil Pressure. The utterance characteristic form lists 10 and omits those two. "
    "The lists disagree, so this case stays needs_information."
)
ABSENT = {
    "iot_knowledge_query": (
        "The official sample registry lists sites MAIN and NORTH and the assets in "
        "asset_profile_sample.json. This utterance asks for a site, asset, or reading that registry does not contain."
    ),
    "iot_data_query": (
        "The official Chiller 6 series does not cover the asset or the dates this utterance asks for. "
        "Missing readings are not invented."
    ),
    "fmsr_knowledge_query": (
        "The official failure-code sample is a generic ten-row list, and failure_modes_sample.json is an "
        "upstream synthetic pump sample marked exhaustive false. Neither is the Chiller 6 failure-mode catalog."
    ),
    "workorder_decision_support": (
        "The official work-order sample has three rows (1000045 on CHILLER6, 1000046 on PUMP3, 1000050 on AHU2). "
        "It does not include the CWC04009 or CWC04013 history this utterance asks for."
    ),
    "workorder_knowledge_query": (
        "The official work-order sample has three rows (1000045 on CHILLER6, 1000046 on PUMP3, 1000050 on AHU2). "
        "It does not include the CWC04009 or CWC04013 history this utterance asks for."
    ),
    "workorder_prediction": (
        "The official work-order sample has three rows and no CWC04009 or CWC04013 history to predict from."
    ),
    "multiagent_knowledge_query": (
        "This utterance needs a multi-agent or anomaly-detector result. The official Chiller 6 series starts "
        "on 2020-06-01, so the week of 2020-04-27 is outside the file. Scenario 3's anomalies_found flag is "
        "an upstream detector output and is not copied into the device record."
    ),
}

_TELEMETRY_CACHE = {}


def file_sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_committed_files():
    """Check the small official files in Git against the manifest. No network."""
    pinned = MANIFEST["committed_files"]
    for name, spec in pinned.items():
        path = FIXTURE_DIR / name
        raw = path.read_bytes()
        if len(raw) != spec["bytes"] or hashlib.sha256(raw).hexdigest() != spec["sha256"]:
            raise ValueError("official fixture hash mismatch: " + name)
    return sorted(pinned)


def _csv_rows(name):
    with (FIXTURE_DIR / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_committed():
    verify_committed_files()
    profile = json.loads((FIXTURE_DIR / "asset_profile_sample.json").read_text(encoding="utf-8"))
    fmea = json.loads((FIXTURE_DIR / "failure_modes_sample.json").read_text(encoding="utf-8"))
    return {
        "profile": profile,
        "work_orders": _csv_rows("workorders.csv"),
        "failure_codes": _csv_rows("failure_code_sample.csv"),
        "fmea": fmea,
        "catalogs": {
            "assets": _csv_rows("catalog_assets.csv"),
            "failure_modes": _csv_rows("catalog_failure_modes.csv"),
            "sensors": _csv_rows("catalog_sensors.csv"),
        },
    }


def resolve_telemetry_path():
    override = os.environ.get("ASSETOPS_IOT_CHILLER")
    if override:
        return Path(override)
    if RUNTIME_CHILLER.is_file():
        return RUNTIME_CHILLER
    return FIXTURE_DIR / "chiller_6_excerpt.json"


def summarize_telemetry(rows, coverage, digest):
    if len(rows) < 2:
        raise ValueError("telemetry needs the official endpoints")
    counts = {}
    for row in rows:
        for key, value in row.items():
            if key in {"asset_id", "timestamp"} or value is None or value == "":
                continue
            counts[key] = counts.get(key, 0) + 1
    pin = MANIFEST["chiller_6"]
    if coverage == "official_file":
        if len(rows) != pin["rows"] or rows[0]["timestamp"] != pin["start"] or rows[-1]["timestamp"] != pin["end"]:
            raise ValueError("chiller_6.json does not match the pinned span")
        if counts.get(FLOW_SENSOR) != pin["condenser_water_flow_observations"]:
            raise ValueError("condenser water flow observation count does not match the pin")
        if counts.get(LOADED_SENSOR) != pin["percent_loaded_observations"]:
            raise ValueError("percent loaded observation count does not match the pin")
    return {
        "coverage": coverage,
        "source_path": pin["upstream_path"],
        "github_commit": COMMIT,
        "license": MANIFEST["license"],
        "sha256": digest,
        "loaded_rows": len(rows),
        "start": rows[0]["timestamp"],
        "end": rows[-1]["timestamp"],
        "observation_counts": counts,
        "endpoints": [rows[0], rows[-1]],
        "full_file": {
            "loaded": coverage == "official_file",
            "rows": pin["rows"],
            "start": pin["start"],
            "end": pin["end"],
            "sha256": pin["sha256"],
            "note": "27 June 2020 through 30 June 2020 are not in the official file.",
        },
    }


def read_telemetry(path=None):
    path = Path(path) if path else resolve_telemetry_path()
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    cached = _TELEMETRY_CACHE.get(key)
    if cached:
        return cached
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    full = MANIFEST["chiller_6"]["sha256"]
    excerpt = MANIFEST["committed_files"]["chiller_6_excerpt.json"]["sha256"]
    if digest == full:
        coverage = "official_file"
    elif digest == excerpt:
        coverage = "excerpt"
    else:
        raise ValueError("telemetry file matches neither the full Chiller 6 series nor the committed excerpt")
    rows = json.loads(raw)
    summary = summarize_telemetry(rows, coverage, digest)
    _TELEMETRY_CACHE[key] = (rows, summary)
    return rows, summary


def work_order_counts(orders):
    main = [row for row in orders if row["siteid"] == "MAIN"]
    corrective = [row for row in main if row["worktype"] == "CM"]
    return {"main_site": len(main), "main_site_corrective": len(corrective)}


def _sensor_words(name):
    skip = {"chiller", "6"}
    return [word for word in re.findall(r"[a-z0-9]+", name.lower()) if word not in skip]


def matching_sensors(description, sensors):
    text = description.lower()
    return [name for name in sensors if _sensor_words(name) and all(word in text for word in _sensor_words(name))]


def scenario3_inputs(sample, telemetry):
    """Fields that can be read without running the upstream anomaly detector."""
    chiller = next(asset for asset in sample["profile"] if asset["assetnum"] == "Chiller 6")
    waiting = [
        row for row in sample["work_orders"]
        if row["siteid"] == "MAIN" and row["status"] == "WAPPR" and "anomaly" in row["description"].lower()
    ]
    if len(waiting) != 1:
        raise ValueError("expected one awaiting-approval anomaly work order at MAIN")
    matched = matching_sensors(waiting[0]["description"], chiller["sensors"])
    result = {
        "work_order": waiting[0]["wonum"],
        "asset": chiller["assetnum"],
        "sensor": matched[0] if len(matched) == 1 else None,
        "sensor_matches": matched,
    }
    if telemetry["coverage"] == "official_file" and result["sensor"]:
        result["observations"] = telemetry["observation_counts"][result["sensor"]]
        result["start"] = telemetry["start"]
        result["end"] = telemetry["end"]
    return result


def _registry(profile):
    rows = []
    for asset in profile:
        eval_id = EVAL_IDS[asset["assetnum"]]
        if not DEVICE_ID.fullmatch(eval_id):
            raise ValueError("eval device id is illegal: " + eval_id)
        rows.append({
            "assetnum": asset["assetnum"],
            "siteid": asset["siteid"],
            "assettype": asset["assettype"],
            "description": asset["description"],
            "eval_device_id": eval_id,
            "id_mapping": "official assetnum stored on a device id this schema accepts",
        })
    return rows


def _shell(asset):
    return {
        "id": EVAL_IDS[asset["assetnum"]],
        "name": asset["description"],
        "type": TYPE_MAP[asset["assettype"]],
        "location": asset.get("location") or asset["siteid"],
        "owner_team": "unspecified",
        "status": asset["status"],
        "data_kind": "official_sample",
    }


def _shared_block(sample, telemetry):
    return {
        "data_kind": "official_sample",
        "license": MANIFEST["license"],
        "github_commit": COMMIT,
        "repository": MANIFEST["repository"],
        "registry": _registry(sample["profile"]),
        "failure_code_sample": {
            "scope": "generic sample, not the Chiller 6 failure-mode catalog",
            "rows": sample["failure_codes"],
        },
        "failure_mode_sample": sample["fmea"],
        "catalogs": {
            "note": "One-row taxonomy files shipped with the scenario sample. They do not list Chiller 6 failure modes.",
            "assets": sample["catalogs"]["assets"],
            "failure_modes": sample["catalogs"]["failure_modes"],
            "sensors": sample["catalogs"]["sensors"],
        },
        "telemetry": telemetry,
    }


def official_manuals(sample):
    chiller = next(asset for asset in sample["profile"] if asset["assetnum"] == "Chiller 6")
    sensors = ", ".join(chiller["sensors"])
    codes = "; ".join(row["code"] + " " + row["description"] for row in sample["failure_codes"])
    modes = ", ".join(sample["fmea"][0]["failure_modes"])
    sites = sorted({asset["siteid"] for asset in sample["profile"]})
    main_assets = [asset["assetnum"] for asset in sample["profile"] if asset["siteid"] == "MAIN"]
    return [
        {
            "id": "AOB-SITE-INDEX",
            "device_type": "general",
            "title": "Official asset profile sample sites",
            "body": (
                f"Official sample sites: {', '.join(sites)}. MAIN assets: {', '.join(main_assets)}. "
                "NORTH assets: AHU2. This is asset_profile_sample.json, not an unshipped site export."
            ),
            "source": SOURCE_LABEL + " src/couchdb/scenarios_data/shared/iot/asset_profile_sample.json",
            "version": COMMIT[:12],
        },
        {
            "id": "AOB-CH6-SENSORS",
            "device_type": "chiller",
            "title": "Official Chiller 6 sensor list",
            "body": (
                "Asset profile sample for assetnum Chiller 6 at site MAIN, location MAIN-MECH-CH6. Sensors: "
                + sensors + ". This profile list is not a failure ranking and does not by itself authorize a draft."
            ),
            "source": SOURCE_LABEL + " src/couchdb/scenarios_data/shared/iot/asset_profile_sample.json",
            "version": COMMIT[:12],
        },
        {
            "id": "AOB-FC-SAMPLE",
            "device_type": "general",
            "title": "Official generic failure code sample",
            "body": (
                "Codes " + codes + ". This generic sample is not the Chiller 6 failure-mode catalog."
            ),
            "source": SOURCE_LABEL + " src/couchdb/scenarios_data/shared/failure_code/failure_code_sample.csv",
            "version": COMMIT[:12],
        },
        {
            "id": "AOB-FMEA-PUMP-SAMPLE",
            "device_type": "pump",
            "title": "Upstream synthetic pump failure mode sample",
            "body": (
                "Asset class pump. Modes: " + modes + ". The upstream file says source synthetic sample and "
                "exhaustive false. This is not a chiller catalog."
            ),
            "source": SOURCE_LABEL + " src/couchdb/scenarios_data/shared/fmea/failure_modes_sample.json",
            "version": COMMIT[:12],
        },
    ]


def _history_order(row):
    device_id = WORK_ORDER_DEVICES[row["assetnum"]]
    order = {
        "id": "WO-" + row["wonum"],
        "device_id": device_id,
        "summary": row["description"],
        "status": row["status"],
        "data_kind": "official_sample",
        "license": MANIFEST["license"],
        "github_commit": COMMIT,
        "source": "src/couchdb/scenarios_data/shared/work_order/workorders.csv",
        "eval_device_id": device_id,
        "official_assetnum": row["assetnum"],
    }
    order.update(row)
    return order


def import_official_sample(store, telemetry_path=None):
    """Attach the official sample to an eval database. The packaged corpus hash stays put."""
    before = store.corpus_sha256
    sample = load_committed()
    _rows, telemetry = read_telemetry(telemetry_path)
    shared = _shared_block(sample, telemetry)
    by_asset = {asset["assetnum"]: asset for asset in sample["profile"]}
    for asset in sample["profile"]:
        eval_id = EVAL_IDS[asset["assetnum"]]
        try:
            current = store.device(eval_id)
        except NotFoundError:
            current = _shell(asset)
        block = {
            "profile": asset,
            "eval_device_id": eval_id,
            "official_assetnum": asset["assetnum"],
        }
        if eval_id == "CH-6":
            block.update(shared)
        elif asset["assettype"] in {"PUMP", "HYDRAULIC_PUMP"}:
            block["failure_mode_sample"] = sample["fmea"]
        current = dict(current)
        current["official_sample"] = block
        store.upsert_device(current)
    for row in sample["work_orders"]:
        store.upsert_history_order(_history_order(row))
    inserted = [manual["id"] for manual in official_manuals(sample) if store.insert_manual(manual)]
    if store.corpus_sha256 != before:
        raise ValueError("official import changed the packaged corpus hash")
    return {
        "telemetry_coverage": telemetry["coverage"],
        "manuals_inserted": inserted,
        "work_order_counts": work_order_counts(sample["work_orders"]),
        "scenario3": scenario3_inputs(sample, telemetry),
        "registry_assets": [asset["assetnum"] for asset in sample["profile"]],
        "chiller_profile": by_asset["Chiller 6"],
    }


def context_for(upstream_id):
    if upstream_id in LOOKUP:
        kind, answers = "lookup", True
        topic = LOOKUP[upstream_id]
    elif upstream_id in PARTIAL:
        kind, answers = "partial", False
        topic = PARTIAL[upstream_id]
    else:
        kind, answers, topic = "absent", False, None
    return {
        "context_class": kind,
        "topic": topic,
        "answers_lookup": answers,
        "official_sample_supports_draft": False,
        "github_commit": COMMIT,
        "license": MANIFEST["license"],
    }


def gap_for(upstream_id, category):
    if upstream_id in LOOKUP:
        return LOOKUP_GAP
    if upstream_id in {9, 12}:
        return JUNE_GAP
    if upstream_id in {104, 603}:
        return SENSOR_GAP
    return ABSENT[category]


def apply_official_annotations(cases, adaptation_ids, mapping_note):
    """Record which frozen cases the official sample can answer. Splits are untouched."""
    preserved = {int(item) for item in adaptation_ids}
    for case in cases:
        case["official_context"] = context_for(case["upstream_id"])
        if case["upstream_id"] in preserved:
            continue
        mapped = mapping_note.strip() in (case.get("data_gap") or "")
        case["data_gap"] = gap_for(case["upstream_id"], case["category"])
        if mapped:
            case["data_gap"] += mapping_note
    return cases


def official_counts(cases):
    counts = {"lookup": [], "partial": [], "absent": []}
    for case in cases:
        kind = (case.get("official_context") or {}).get("context_class", "absent")
        counts[kind].append(case["upstream_id"])
    return {key: value for key, value in counts.items()}
