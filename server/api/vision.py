from __future__ import annotations

import math
from typing import List, Tuple

import cv2
import numpy as np


def _l2_normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm < 1e-9:
        return vector
    return vector / norm


def _enhance_image(image_bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    enhanced = cv2.merge((l_channel, a_channel, b_channel))
    enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    return cv2.bilateralFilter(enhanced, 5, 50, 50)


def _center_crop(image: np.ndarray, ratio: float = 0.82) -> np.ndarray:
    height, width = image.shape[:2]
    crop_height = max(40, int(height * ratio))
    crop_width = max(40, int(width * ratio))
    top = max(0, (height - crop_height) // 2)
    left = max(0, (width - crop_width) // 2)
    return image[top : top + crop_height, left : left + crop_width]


def _hsv_histogram_features(image_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(cv2.resize(image_bgr, (96, 96), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2HSV)
    features = []
    for channel in range(3):
        hist = cv2.calcHist([hsv], [channel], None, [16], [0, 256]).flatten().astype(np.float32)
        features.append(_l2_normalize(hist))
    return np.concatenate(features, axis=0)


def _color_layout_features(image_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(cv2.resize(image_bgr, (64, 64), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2HSV)
    cells = []
    for row in range(4):
        for col in range(4):
            cell = hsv[row * 16 : (row + 1) * 16, col * 16 : (col + 1) * 16]
            mean = cell.mean(axis=(0, 1)).astype(np.float32) / 255.0
            std = cell.std(axis=(0, 1)).astype(np.float32) / 255.0
            cells.append(np.concatenate([mean, std], axis=0))
    return np.concatenate(cells, axis=0)


def _edge_orientation_features(image_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(cv2.resize(image_bgr, (64, 64), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude, angle = cv2.cartToPolar(grad_x, grad_y, angleInDegrees=True)
    angle = np.mod(angle, 180.0)

    bins = np.linspace(0.0, 180.0, 9, dtype=np.float32)
    features = []
    for row in range(4):
        for col in range(4):
            mag_cell = magnitude[row * 16 : (row + 1) * 16, col * 16 : (col + 1) * 16]
            angle_cell = angle[row * 16 : (row + 1) * 16, col * 16 : (col + 1) * 16]
            hist, _ = np.histogram(angle_cell, bins=bins, weights=mag_cell)
            features.append(_l2_normalize(hist.astype(np.float32)))
    return np.concatenate(features, axis=0)


def _dct_features(image_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(cv2.resize(image_bgr, (32, 32), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    gray = gray.astype(np.float32) / 255.0
    dct = cv2.dct(gray)
    low_freq = np.abs(dct[:8, :8]).flatten().astype(np.float32)
    return _l2_normalize(low_freq)


def _view_features(image_bgr: np.ndarray) -> np.ndarray:
    features = [
        _hsv_histogram_features(image_bgr),
        _color_layout_features(image_bgr),
        _edge_orientation_features(image_bgr),
        _dct_features(image_bgr),
    ]
    return np.concatenate(features, axis=0)


def image_embedding_bgr(img_bgr: np.ndarray) -> List[float]:
    """Compact embedding for product packages.

    The vector mixes color layout, edges, and low-frequency structure for the
    whole image and a center crop. This is stronger than a global color
    histogram while still being lightweight and CPU friendly.
    """
    if img_bgr is None or img_bgr.size == 0:
        return [0.0] * 672

    enhanced = _enhance_image(img_bgr)
    center = _center_crop(enhanced)
    embedding = np.concatenate([_view_features(enhanced), _view_features(center)], axis=0)
    embedding = _l2_normalize(embedding.astype(np.float32))
    return embedding.tolist()


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    score = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        score += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 1e-12 or norm_b <= 1e-12:
        return 0.0
    return float(score / math.sqrt(norm_a * norm_b))


def top_k_similar(query: List[float], samples: List[Tuple[int, str, List[float]]], k: int = 5):
    scored = []
    for product_id, product_name, embedding in samples:
        scored.append((product_id, product_name, cosine_similarity(query, embedding)))
    scored.sort(key=lambda item: item[2], reverse=True)
    return scored[:k]


def aggregate_by_product(scored: List[Tuple[int, str, float]], top_n: int = 5):
    best_scores = {}
    for product_id, product_name, similarity in scored:
        key = (product_id, product_name)
        best_scores[key] = max(best_scores.get(key, 0.0), similarity)

    aggregated = [(product_id, product_name, similarity) for (product_id, product_name), similarity in best_scores.items()]
    aggregated.sort(key=lambda item: item[2], reverse=True)
    return aggregated[:top_n]
