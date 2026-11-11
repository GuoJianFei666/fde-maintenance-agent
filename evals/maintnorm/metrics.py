"""Word-level precision, recall, and error reduction rate.

Definitions follow van der Goot (2019) as used by Bikaun, Hodkiewicz, and Liu
(2024), Appendix A:

- TP: a token needed a change and the prediction matches the gold normalisation.
- FP: a token needed no change and the prediction changes it.
- FN: a token needed a change and the prediction does not match gold.
  A wrong replacement is FN, not also FP.

E.R.R. = (TP - FP) / (TP + FN). Each raw token is one item, so a 1:N gold
string is one decision. Alignment is given by the .norm line; this is not the
paper's unconstrained decoder alignment.
"""


def parse_norm(text):
    sentences = []
    current = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            if current:
                sentences.append(current)
                current = []
            continue
        if "\t" not in line:
            raise ValueError(f"norm_line_missing_tab:{line_number}")
        raw, gold = line.split("\t", 1)
        if raw == "":
            raise ValueError(f"empty_raw_token:{line_number}")
        current.append((raw, gold))
    if current:
        sentences.append(current)
    return sentences


def render(tokens):
    return " ".join(token for token in tokens if token)


def score_tokens(pairs):
    """pairs is an iterable of (raw, gold, predicted)."""
    tp = fp = fn = 0
    for raw, gold, predicted in pairs:
        if predicted == gold:
            if raw != gold:
                tp += 1
        elif raw == gold:
            fp += 1
        else:
            fn += 1
    return {"tp": tp, "fp": fp, "fn": fn}


def combine(counts):
    total = {"tp": 0, "fp": 0, "fn": 0}
    for item in counts:
        for key in total:
            total[key] += item[key]
    return rates(total)


def rates(counts):
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    err = (tp - fp) / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "err": err,
            "precision_percent": round(precision * 100, 1),
            "recall_percent": round(recall * 100, 1),
            "err_percent": round(err * 100, 1)}
