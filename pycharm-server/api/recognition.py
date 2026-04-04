from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

from .ocr import OcrResult
from .vision import cosine_similarity

TOKEN_RE = re.compile(r"[a-z0-9]+")
FAT_PERCENT_RE = re.compile(r"(\d+(?:[\.,]\d+)?)\s*%")

STOPWORDS = {
    "food",
    "fresh",
    "gram",
    "grams",
    "kg",
    "g",
    "ml",
    "l",
    "pcs",
    "piece",
    "pieces",
    "pack",
    "opakowanie",
    "produkt",
    "super",
    "extra",
}


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_value).strip().casefold()


def tokenize(value: str) -> List[str]:
    tokens = TOKEN_RE.findall(normalize_text(value))
    return [token for token in tokens if len(token) > 1 and token not in STOPWORDS]


def _best_line_similarity(text: str, lines: Iterable[str]) -> float:
    if not text:
        return 0.0
    best = 0.0
    for line in lines:
        if not line:
            continue
        ratio = SequenceMatcher(None, text, line).ratio()
        if ratio > best:
            best = ratio
    return best


def _parse_measurement_string(value: Optional[str]) -> Dict[str, Optional[float]]:
    parsed: Dict[str, Optional[float]] = {
        "volume_l": None,
        "weight_g": None,
        "pieces": None,
    }
    if not value:
        return parsed

    normalized = normalize_text(value).replace(",", ".")

    piece_match = re.search(r"(\d+)\s*(?:pcs?|pieces?|szt|x)\b", normalized)
    if piece_match:
        parsed["pieces"] = float(piece_match.group(1))

    volume_match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|l)\b", normalized)
    if volume_match:
        amount = float(volume_match.group(1))
        parsed["volume_l"] = amount / 1000.0 if volume_match.group(2) == "ml" else amount

    weight_match = re.search(r"(\d+(?:\.\d+)?)\s*(g|kg)\b", normalized)
    if weight_match:
        amount = float(weight_match.group(1))
        parsed["weight_g"] = amount * 1000.0 if weight_match.group(2) == "kg" else amount

    return parsed


def _parse_fat_percent(value: str) -> Optional[float]:
    match = FAT_PERCENT_RE.search(value or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _measurement_similarity(expected: float, actual: float) -> float:
    if expected <= 0 or actual <= 0:
        return 0.0
    ratio = abs(expected - actual) / max(expected, actual)
    if ratio <= 0.03:
        return 1.0
    if ratio <= 0.08:
        return 0.9
    if ratio <= 0.15:
        return 0.7
    if ratio <= 0.25:
        return 0.45
    return 0.0


def _product_terms(product: Dict[str, Any]) -> List[str]:
    aliases = product.get("aliases") or []
    brand = product.get("brand")
    return [str(product.get("name", "")), *(str(alias) for alias in aliases), str(brand or "")]


def _score_text(product: Dict[str, Any], ocr_result: OcrResult) -> float:
    normalized_ocr = normalize_text(ocr_result.text)
    if not normalized_ocr:
        return 0.0

    ocr_lines = [normalize_text(line) for line in (ocr_result.text or "").splitlines() if line.strip()]
    ocr_tokens = set(tokenize(ocr_result.text))
    product_strings = [normalize_text(term) for term in _product_terms(product) if normalize_text(term)]
    if not product_strings:
        return 0.0

    product_tokens = set()
    for term in product_strings:
        product_tokens.update(tokenize(term))

    overlap = 0.0
    if product_tokens:
        overlap = len(product_tokens & ocr_tokens) / len(product_tokens)

    substring_bonus = 0.0
    for term in product_strings:
        if term and term in normalized_ocr:
            substring_bonus = max(substring_bonus, 1.0)

    fuzzy_scores = [_best_line_similarity(term, ocr_lines) for term in product_strings]
    fuzzy_score = max(fuzzy_scores, default=0.0)

    token_density = 0.0
    if ocr_tokens and product_tokens:
        token_density = len(product_tokens & ocr_tokens) / len(ocr_tokens)

    score = (overlap * 0.45) + (fuzzy_score * 0.35) + (substring_bonus * 0.15) + (token_density * 0.05)
    return max(0.0, min(1.0, score))


def _score_measurements(product: Dict[str, Any], ocr_result: OcrResult) -> float:
    measurements = []
    ocr_measurement = _parse_measurement_string(ocr_result.net)

    if product.get("volume_l") is not None and ocr_measurement["volume_l"] is not None:
        measurements.append(_measurement_similarity(float(product["volume_l"]), float(ocr_measurement["volume_l"])))
    if product.get("weight_g") is not None and ocr_measurement["weight_g"] is not None:
        measurements.append(_measurement_similarity(float(product["weight_g"]), float(ocr_measurement["weight_g"])))

    product_fat_values = []
    for term in _product_terms(product):
        fat_value = _parse_fat_percent(str(term))
        if fat_value is not None:
            product_fat_values.append(fat_value)

    if product_fat_values and ocr_result.fat_percent is not None:
        best_diff = min(abs(value - ocr_result.fat_percent) for value in product_fat_values)
        if best_diff <= 0.15:
            measurements.append(1.0)
        elif best_diff <= 0.35:
            measurements.append(0.75)
        elif best_diff <= 0.6:
            measurements.append(0.4)
        else:
            measurements.append(0.0)

    if not measurements:
        return 0.0

    return float(sum(measurements) / len(measurements))


def _mean_embedding(embeddings: List[List[float]]) -> Optional[List[float]]:
    if not embeddings:
        return None
    arr = np.asarray(embeddings, dtype=np.float32)
    mean = arr.mean(axis=0)
    norm = float(np.linalg.norm(mean))
    if norm > 1e-9:
        mean = mean / norm
    return mean.astype(np.float32).tolist()


def rank_catalog(
    query_embedding: List[float],
    ocr_result: OcrResult,
    catalog: List[Dict[str, Any]],
    *,
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    has_ocr_text = bool(normalize_text(ocr_result.text))
    embedding_size = len(query_embedding)

    for product in catalog:
        embeddings = [embedding for embedding in (product.get("embeddings") or []) if len(embedding) == embedding_size]
        if not embeddings:
            image_score = 0.0
            best_sample_score = 0.0
            prototype_score = 0.0
        else:
            sample_scores = [cosine_similarity(query_embedding, embedding) for embedding in embeddings]
            best_sample_score = max(sample_scores, default=0.0)

            prototype_embedding = _mean_embedding(embeddings)
            prototype_score = cosine_similarity(query_embedding, prototype_embedding or []) if prototype_embedding else 0.0
            image_score = (best_sample_score * 0.58) + (prototype_score * 0.42)

        text_score = _score_text(product, ocr_result)
        measurement_score = _score_measurements(product, ocr_result)

        if has_ocr_text:
            final_score = (image_score * 0.62) + (text_score * 0.28) + (measurement_score * 0.10)
        else:
            final_score = (image_score * 0.94) + (measurement_score * 0.06)

        if text_score >= 0.85:
            final_score += 0.025
        if measurement_score >= 0.75:
            final_score += 0.02

        final_score = max(0.0, min(1.0, final_score))
        ranked.append(
            {
                "id": product["id"],
                "name": product["name"],
                "brand": product.get("brand"),
                "aliases": list(product.get("aliases") or []),
                "pieces": int(product.get("pieces") or 1),
                "volume_l": product.get("volume_l"),
                "weight_g": product.get("weight_g"),
                "confidence": round(final_score, 3),
                "image_score": round(image_score, 3),
                "text_score": round(text_score, 3),
                "measurement_score": round(measurement_score, 3),
                "sample_count": len(embeddings),
            }
        )

    ranked.sort(
        key=lambda item: (
            item["confidence"],
            item["text_score"],
            item["image_score"],
            item["sample_count"],
        ),
        reverse=True,
    )
    return ranked[:top_n]
