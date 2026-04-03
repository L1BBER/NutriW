from __future__ import annotations

import math
from typing import List, Tuple

import cv2
import numpy as np


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return v
    return v / n


def image_embedding_bgr(img_bgr: np.ndarray) -> List[float]:
    """Lightweight embedding: concatenated HSV histograms.

    This is NOT a SOTA model, but it works as a training-friendly baseline
    without GPU and without huge dependencies.
    """
    if img_bgr is None or img_bgr.size == 0:
        return [0.0] * 96

    img = cv2.resize(img_bgr, (224, 224), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # 32 bins for H, 32 for S, 32 for V
    feats = []
    for ch in range(3):
        hist = cv2.calcHist([hsv], [ch], None, [32], [0, 256])
        hist = hist.flatten().astype(np.float32)
        hist = _l2_normalize(hist)
        feats.append(hist)

    emb = np.concatenate(feats, axis=0)
    emb = _l2_normalize(emb)
    return emb.astype(np.float32).tolist()


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    s = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        s += x * y
        na += x * x
        nb += y * y
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return float(s / math.sqrt(na * nb))


def top_k_similar(query: List[float], samples: List[Tuple[int, str, List[float]]], k: int = 5):
    scored = []
    for pid, pname, emb in samples:
        sim = cosine_similarity(query, emb)
        scored.append((pid, pname, sim))
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:k]


def aggregate_by_product(scored: List[Tuple[int, str, float]], top_n: int = 5):
    # Take max sim per product
    best = {}
    for pid, pname, sim in scored:
        key = (pid, pname)
        best[key] = max(best.get(key, 0.0), sim)

    out = [(pid, pname, sim) for (pid, pname), sim in best.items()]
    out.sort(key=lambda x: x[2], reverse=True)
    return out[:top_n]
