"""Recall, MRR, and nDCG for one relevant manual chunk per query."""

import math

from evals.assetopsbench.metrics import percentile


def first_rank(retrieved_ids, relevant_ids):
    relevant = set(relevant_ids)
    for index, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in relevant:
            return index
    return None


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def summarise(ranks, latencies, *, recall_ks=(1, 3), ndcg_k=3):
    recall = {}
    for k in recall_ks:
        hits = [1.0 if rank is not None and rank <= k else 0.0 for rank in ranks]
        recall[f"recall@{k}"] = _mean(hits)
    reciprocal = [0.0 if rank is None else 1.0 / rank for rank in ranks]
    gains = [1.0 / math.log2(rank + 1) if rank is not None and rank <= ndcg_k else 0.0 for rank in ranks]
    return {
        "query_count": len(ranks),
        **recall,
        "mrr": _mean(reciprocal),
        f"ndcg@{ndcg_k}": _mean(gains),
        "latency_ms_mean": _mean(latencies) if latencies else None,
        "latency_ms_p50": percentile(latencies, 50),
    }
