"""Score exact token spans and five top-level categories, including nested entities."""

from collections import Counter


def span_keys(entities):
    return {(entity["start"], entity["end"], entity["type"].split("/")[0]) for entity in entities}


def metrics(cases):
    counts = Counter()
    by_type = {}
    exact = 0
    for case in cases:
        expected = span_keys(case["expected"])
        predicted = span_keys(case["predicted"])
        exact += expected == predicted
        for label in {key[2] for key in expected | predicted}:
            tally = by_type.setdefault(label, Counter())
            gold = {key for key in expected if key[2] == label}
            actual = {key for key in predicted if key[2] == label}
            tally.update(tp=len(gold & actual), fp=len(actual - gold), fn=len(gold - actual))
        counts.update(tp=len(expected & predicted), fp=len(predicted - expected), fn=len(expected - predicted))

    def scores(tally):
        tp, fp, fn = (tally[key] for key in ("tp", "fp", "fn"))
        return {"tp": tp, "fp": fp, "fn": fn,
                "precision": tp / (tp + fp) if tp + fp else 0.0,
                "recall": tp / (tp + fn) if tp + fn else 0.0,
                "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}

    return {"micro": scores(counts), "by_type": {label: scores(tally) for label, tally in sorted(by_type.items())},
            "exact_record_count": exact, "evaluated_record_count": len(cases),
            "scoring": "Exact (start,end,top-level type) set matching; zero denominator -> 0; failed calls -> empty prediction"}
