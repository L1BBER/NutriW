from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional

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


def _parse_net(text: str) -> Optional[str]:
    m = re.search(r"(\d+(?:[\.,]\d+)?)\s*(kg|g|ml|l)\b", text.lower())
    if not m:
        return None
    val = m.group(1).replace(',', '.')
    unit = m.group(2)
    return f"{val} {unit}"


def _parse_nutrition(text: str) -> Dict[str, Optional[float]]:
    # Heuristic: look for kcal and macros numbers near words
    lower = text.lower()

    def find_number(patterns):
        for p in patterns:
            m = re.search(p, lower)
            if m:
                try:
                    return float(m.group(1).replace(',', '.'))
                except Exception:
                    continue
        return None

    kcal = find_number([
        r"kcal\s*(\d+(?:[\.,]\d+)?)",
        r"(\d+(?:[\.,]\d+)?)\s*kcal",
    ])

    protein = find_number([
        r"białk\w*\s*(\d+(?:[\.,]\d+)?)",
        r"protein\s*(\d+(?:[\.,]\d+)?)",
        r"p\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\b",
    ])

    fat = find_number([
        r"tłuszcz\w*\s*(\d+(?:[\.,]\d+)?)",
        r"fat\s*(\d+(?:[\.,]\d+)?)",
        r"f\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\b",
    ])

    carbs = find_number([
        r"węglowodan\w*\s*(\d+(?:[\.,]\d+)?)",
        r"carb\w*\s*(\d+(?:[\.,]\d+)?)",
        r"c\s*[:=]?\s*(\d+(?:[\.,]\d+)?)\b",
    ])

    return {"kcal": kcal, "p": protein, "f": fat, "c": carbs}


def _parse_fat_percent(text: str) -> Optional[float]:
    """Best-effort parse of % value from label (e.g. '3,2%').

    For milk and many dairy products the fat percentage is prominent.
    This is heuristic; if multiple percentages exist, it takes the first match.
    """
    m = re.search(r"(\d+(?:[\.,]\d+)?)\s*%", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(',', '.'))
    except Exception:
        return None


def run_ocr(image_bgr: np.ndarray) -> OcrResult:
    """OCR step.

    - Tries to use easyocr if available.
    - If not installed, returns empty text with low confidence.
    """
    try:
        import easyocr  # type: ignore

        reader = easyocr.Reader(['uk', 'pl', 'en'], gpu=False)
        # easyocr expects RGB
        rgb = image_bgr[:, :, ::-1]
        results = reader.readtext(rgb)
        # results: list of (bbox, text, conf)
        texts = []
        confs = []
        for _, t, c in results:
            if t and t.strip():
                texts.append(t)
                confs.append(float(c))
        text = "\n".join(texts).strip()
        conf = float(sum(confs) / len(confs)) if confs else 0.2
    except Exception:
        text = ""
        conf = 0.2

    net = _parse_net(text) if text else None
    fat_percent = _parse_fat_percent(text) if text else None
    n = _parse_nutrition(text) if text else {"kcal": None, "p": None, "f": None, "c": None}

    return OcrResult(
        text=text,
        net=net,
        fat_percent=fat_percent,
        kcal_100=n.get("kcal"),
        p_100=n.get("p"),
        f_100=n.get("f"),
        c_100=n.get("c"),
        confidence=conf,
    )
