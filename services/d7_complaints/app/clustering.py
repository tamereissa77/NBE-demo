"""D7 trends: let the data choose the number of clusters.

The baseline asks k-means for exactly 10 clusters. Here k-means runs for every k in a range, several
restarts each, and the k with the best silhouette score wins (how much closer complaints sit to their
own cluster than to the nearest other one). numpy only, fixed seeds: the same vectors give the same result.

Switched on by data/seed/d7/trends.json; without that file the service keeps the fixed k.
"""
import json
from pathlib import Path

import numpy as np

CONFIG = Path("/data/seed/d7/trends.json")


def load_config() -> dict | None:
    return json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else None


def _kmeans(x: np.ndarray, k: int, seed: int, iters: int = 50) -> tuple[np.ndarray, float]:
    """Spherical k-means with k-means++ seeding. Returns labels and mean similarity to the own centre."""
    rng = np.random.default_rng(seed)
    centers = [x[rng.integers(len(x))]]
    for _ in range(k - 1):
        d = np.clip(1 - np.max(x @ np.array(centers).T, axis=1), 0, None) ** 2
        centers.append(x[rng.choice(len(x), p=d / d.sum())])
    c = np.array(centers)
    for _ in range(iters):
        labels = np.argmax(x @ c.T, axis=1)
        new = np.stack([x[labels == j].mean(0) if (labels == j).any() else c[j] for j in range(k)])
        c = new / np.linalg.norm(new, axis=1, keepdims=True)
    labels = np.argmax(x @ c.T, axis=1)
    return labels, float((x * c[labels]).sum(1).mean())


def _silhouette(dist: np.ndarray, labels: np.ndarray) -> float:
    ks = np.unique(labels)
    if len(ks) < 2:
        return -1.0
    n = len(labels)
    idx = np.searchsorted(ks, labels)
    sums = np.stack([dist[:, labels == j].sum(1) for j in ks], axis=1)
    counts = np.array([(labels == j).sum() for j in ks])
    own = counts[idx]
    a = sums[np.arange(n), idx] / np.maximum(own - 1, 1)
    other = sums / counts
    other[np.arange(n), idx] = np.inf
    b = other.min(1)
    s = (b - a) / np.maximum(a, b)
    s[own == 1] = 0
    return float(s.mean())


def choose_clusters(x: np.ndarray, k_min: int = 4, k_max: int = 16, restarts: int = 8) -> tuple[np.ndarray, dict]:
    """x: L2-normalised vectors. Returns labels (0..k-1) and how k was chosen."""
    dist = 1 - x @ x.T
    scores: dict[int, float] = {}
    best: tuple[float, np.ndarray] | None = None
    for k in range(k_min, min(k_max, len(x) - 1) + 1):
        labels = max((_kmeans(x, k, seed) for seed in range(restarts)), key=lambda r: r[1])[0]
        scores[k] = round(_silhouette(dist, labels), 4)
        if best is None or scores[k] > best[0]:
            best = (scores[k], labels)
    _, remap = np.unique(best[1], return_inverse=True)      # an emptied cluster would leave a gap in the ids
    k = int(remap.max()) + 1
    return remap, {"method": "k-means, k chosen by silhouette score", "k": k, "k_range": [k_min, k_max],
                   "restarts": restarts, "silhouette_by_k": scores}
