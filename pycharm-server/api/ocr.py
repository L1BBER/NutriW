from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class OcrResult:
    text: str
    net: Optional[str]
    fat_percent: Optional[float]
    kcal_100: Optional[float]
    p_100: Optional[float]
    f_100: Optional[float]
    c_100: Optional[float]
    confidence: float
    available: bool
    warning: Optional[str]


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_value).strip().casefold()


def _parse_net(text: str) -> Optional[str]:
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*(kg|g|ml|l)\b", _normalize_text(text))
    if not match:
        return None
    value = match.group(1).replace(",", ".")
    unit = match.group(2)
    return f"{value} {unit}"


def _parse_nutrition(text: str) -> Dict[str, Optional[float]]:
    lower = _normalize_text(text)

    def find_number(patterns: List[str]) -> Optional[float]:
        for pattern in patterns:
            match = re.search(pattern, lower)
            if not match:
                continue
            try:
                return float(match.group(1).replace(",", "."))
            except ValueError:
                continue
        return None

    kcal = find_number(
        [
            r"kcal\s*(\d+(?:[\.,]\d+)?)",
            r"(\d+(?:[\.,]\d+)?)\s*kcal",
            r"energia\s*(\d+(?:[\.,]\d+)?)\s*kcal",
        ]
    )
    protein = find_number(
        [
            r"bialk\w*\s*(\d+(?:[\.,]\d+)?)",
            r"protein\s*(\d+(?:[\.,]\d+)?)",
            r"proteins?\s*(\d+(?:[\.,]\d+)?)",
            r"p\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\b",
        ]
    )
    fat = find_number(
        [
            r"tluszcz\w*\s*(\d+(?:[\.,]\d+)?)",
            r"fat\s*(\d+(?:[\.,]\d+)?)",
            r"f\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\b",
        ]
    )
    carbs = find_number(
        [
            r"weglowodan\w*\s*(\d+(?:[\.,]\d+)?)",
            r"carb\w*\s*(\d+(?:[\.,]\d+)?)",
            r"c\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\b",
        ]
    )

    return {"kcal": kcal, "p": protein, "f": fat, "c": carbs}


def _parse_fat_percent(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*%", text or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _enhance_contrast(image_bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    enhanced = cv2.merge((l_channel, a_channel, b_channel))
    return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)


def _center_crop(image: np.ndarray, ratio: float = 0.82) -> np.ndarray:
    height, width = image.shape[:2]
    crop_height = max(32, int(height * ratio))
    crop_width = max(32, int(width * ratio))
    top = max(0, (height - crop_height) // 2)
    left = max(0, (width - crop_width) // 2)
    return image[top : top + crop_height, left : left + crop_width]


def _prepare_ocr_variants(image_bgr: np.ndarray) -> List[np.ndarray]:
    enhanced = _enhance_contrast(image_bgr)
    gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    threshold = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11,
    )
    threshold_bgr = cv2.cvtColor(threshold, cv2.COLOR_GRAY2BGR)
    sharpened = cv2.addWeighted(enhanced, 1.3, cv2.GaussianBlur(enhanced, (0, 0), 2.2), -0.3, 0)
    center = _center_crop(enhanced)
    center_threshold = cv2.cvtColor(
        cv2.adaptiveThreshold(
            cv2.cvtColor(center, cv2.COLOR_BGR2GRAY),
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            9,
        ),
        cv2.COLOR_GRAY2BGR,
    )

    variants = [enhanced, sharpened, threshold_bgr, center, center_threshold]
    return [variant for variant in variants if variant.size]


@lru_cache(maxsize=1)
def _get_easyocr_reader():
    import easyocr  # type: ignore

    return easyocr.Reader(["uk", "pl", "en"], gpu=False)


def _extract_variant_text(results: List[Tuple[object, str, float]]) -> Tuple[List[str], List[float]]:
    lines: List[str] = []
    confidences: List[float] = []
    for _, text, confidence in results:
        cleaned = str(text).strip()
        if not cleaned:
            continue
        lines.append(cleaned)
        confidences.append(float(confidence))
    return lines, confidences


def run_ocr(image_bgr: np.ndarray) -> OcrResult:
    if image_bgr is None or image_bgr.size == 0:
        return OcrResult("", None, None, None, None, None, None, 0.0, False, "Invalid image for OCR.")

    available = True
    warning: Optional[str] = None
    try:
        reader = _get_easyocr_reader()
        variants = _prepare_ocr_variants(image_bgr)

        deduped_lines: Dict[str, Tuple[str, float]] = {}
        all_confidences: List[float] = []

        for variant in variants:
            rgb = cv2.cvtColor(variant, cv2.COLOR_BGR2RGB)
            results = reader.readtext(rgb, detail=1, paragraph=False)
            lines, confidences = _extract_variant_text(results)

            for line, confidence in zip(lines, confidences):
                key = _normalize_text(line)
                previous = deduped_lines.get(key)
                if previous is None or confidence > previous[1]:
                    deduped_lines[key] = (line, confidence)

            all_confidences.extend(confidences)

        ordered_lines = [line for line, _ in sorted(deduped_lines.values(), key=lambda item: item[1], reverse=True)]
        text = "\n".join(ordered_lines).strip()
        confidence = float(sum(all_confidences) / len(all_confidences)) if all_confidences else 0.2
        if not text:
            warning = "OCR engine ran, but no readable text was found in this image."
    except ModuleNotFoundError as exc:
        text = ""
        confidence = 0.0
        available = False
        if exc.name == "easyocr":
            warning = "OCR engine is not installed on the server."
        else:
            warning = "OCR dependency is missing on the server."
    except Exception:
        text = ""
        confidence = 0.2
        warning = "OCR engine failed while analyzing the image."

    net = _parse_net(text) if text else None
    fat_percent = _parse_fat_percent(text) if text else None
    nutrition = _parse_nutrition(text) if text else {"kcal": None, "p": None, "f": None, "c": None}

    return OcrResult(
        text=text,
        net=net,
        fat_percent=fat_percent,
        kcal_100=nutrition.get("kcal"),
        p_100=nutrition.get("p"),
        f_100=nutrition.get("f"),
        c_100=nutrition.get("c"),
        confidence=confidence,
        available=available,
        warning=warning,
    )
