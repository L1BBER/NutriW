from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .text_utils import normalize_text

MEASUREMENT_RE = re.compile(r"(\d+(?:[.,]\d+)?|\d+/\d+)\s*(kg|g|ml|l|pcs?|pieces?|szt\.?|sztuka|sztuki|sztuk|x)\b")
PAREN_MEASUREMENT_RE = re.compile(r"\(\s*(\d+(?:[.,]\d+)?|\d+/\d+)\s*(kg|g|ml|l)\s*\)", re.IGNORECASE)
INLINE_MEASUREMENT_RE = re.compile(r"(\d+(?:[.,]\d+)?|\d+/\d+)\s*(kg|g|ml|l)\b", re.IGNORECASE)
LEADING_COUNT_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?|\d+/\d+)\b")
WORD_RE = re.compile(r"[a-z0-9]+")
SPLIT_RE = re.compile(r"[,;\n]+")
NOISE_PREFIX_RE = re.compile(
    r"^(?:add|mix|use|take|prepare|combine|with|and|or|dodaj|wymieszaj|uzyj|wez|polacz|z|vziaty|dodaty)\s+",
    re.IGNORECASE,
)
BULLET_PREFIX_RE = re.compile(r"^\s*[-*•·]+\s*")
LETTER_GROUP = r"A-Za-zÀ-ÿĄąĆćĘęŁłŃńÓóŚśŹźŻż"
AMOUNT_TAIL_RE = re.compile(
    rf"(?P<amount>(?:\d+(?:[.,]\d+)?|\d+/\d+|[½⅓⅔¼¾])(?:\s+[{LETTER_GROUP}-]+){{1,4}})\s*$",
    re.UNICODE,
)

PIECE_UNITS = {
    "pc",
    "pcs",
    "piece",
    "pieces",
    "szt",
    "sztuka",
    "sztuki",
    "sztuk",
}
AMOUNT_UNIT_KEYWORDS = PIECE_UNITS | {
    "lyzka",
    "lyzki",
    "lyzek",
    "lyzeczka",
    "lyzeczki",
    "lyzeczek",
    "szklanka",
    "szklanki",
    "szklanek",
    "kostka",
    "kostki",
    "kostek",
    "opakowanie",
    "opakowania",
    "opakowan",
    "porcja",
    "porcje",
    "porcji",
}
AMOUNT_DESCRIPTOR_WORDS = {
    "duza",
    "duzej",
    "duze",
    "mala",
    "malej",
    "male",
    "maly",
    "pol",
    "polowa",
    "half",
    "big",
    "small",
}
HEADER_PREFIXES = (
    "skladniki",
    "ingredients",
)
NON_INGREDIENT_WORDS = {
    "na",
    "for",
    "portion",
    "portions",
    "porcja",
    "porcje",
    "porcji",
    "skladniki",
    "ingredients",
}
UNICODE_FRACTIONS = {"½", "⅓", "⅔", "¼", "¾"}


def parse_recipe_source_text(source_text: str, products: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    source_text = str(source_text or "").strip()
    if not source_text:
        return []

    chunks = [chunk.strip() for chunk in SPLIT_RE.split(source_text) if chunk.strip()]
    if not chunks:
        chunks = [source_text]

    ingredients: List[Dict[str, Any]] = []
    for chunk in chunks:
        ingredients.extend(_parse_recipe_chunk(chunk, products))

    return ingredients


def _parse_recipe_chunk(chunk: str, products: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized_chunk = normalize_text(chunk)
    if not normalized_chunk or _looks_like_header_line(normalized_chunk):
        return []

    matches = _catalog_matches(normalized_chunk, products)
    if len(matches) == 1:
        ingredient = _build_catalog_ingredient(matches[0], chunk, normalized_chunk)
        return [ingredient] if ingredient is not None else []
    if matches:
        ingredients: List[Dict[str, Any]] = []
        for match in matches:
            ingredient = _build_catalog_ingredient(match, chunk, normalized_chunk)
            if ingredient is not None:
                ingredients.append(ingredient)
        return ingredients

    ingredient = _parse_freeform_chunk(chunk)
    return [ingredient] if ingredient is not None else []


def _looks_like_header_line(normalized_chunk: str) -> bool:
    if any(normalized_chunk.startswith(prefix) for prefix in HEADER_PREFIXES):
        return True
    return bool(re.fullmatch(r"na \d+ porcj\w*", normalized_chunk))


def _catalog_matches(normalized_source: str, products: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for product in products:
        terms = [str(product.get("name", "")).strip(), *(str(alias).strip() for alias in product.get("aliases") or [])]
        seen_terms: set[str] = set()
        for term in terms:
            normalized_term = normalize_text(term)
            if len(normalized_term) < 2 or normalized_term in seen_terms:
                continue
            seen_terms.add(normalized_term)
            entries.append(
                {
                    "product": product,
                    "name": str(product.get("name", "")).strip(),
                    "normalized_term": normalized_term,
                    "term_length": len(normalized_term),
                }
            )

    entries.sort(key=lambda entry: entry["term_length"], reverse=True)

    matches: List[Dict[str, Any]] = []
    occupied: List[Tuple[int, int]] = []
    for entry in entries:
        pattern = _term_pattern(entry["normalized_term"])
        for match in pattern.finditer(normalized_source):
            start, end = match.span()
            if any(not (end <= used_start or start >= used_end) for used_start, used_end in occupied):
                continue

            occupied.append((start, end))
            matches.append(
                {
                    "start": start,
                    "end": end,
                    "product": entry["product"],
                    "name": entry["name"],
                }
            )

    matches.sort(key=lambda item: item["start"])
    return matches


def _term_pattern(normalized_term: str) -> re.Pattern[str]:
    escaped = re.escape(normalized_term).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


def _build_catalog_ingredient(
    match: Dict[str, Any],
    raw_chunk: str,
    normalized_source: str,
) -> Optional[Dict[str, Any]]:
    product = match["product"]
    parsed = _parse_chunk_components(raw_chunk, preferred_name=match["name"], grams_per_piece=product.get("grams_per_piece"))
    if parsed is None:
        return None

    fallback_amount, fallback_grams = _extract_measurements(
        normalized_source,
        match["start"],
        match["end"],
        grams_per_piece=product.get("grams_per_piece"),
    )
    if not parsed["amount_text"]:
        parsed["amount_text"] = fallback_amount
    if parsed["grams"] is None:
        parsed["grams"] = fallback_grams

    return {
        "name": parsed["name"],
        "amount_text": parsed["amount_text"],
        "grams": parsed["grams"],
        "required": True,
    }


def _parse_freeform_chunk(raw_chunk: str) -> Optional[Dict[str, Any]]:
    parsed = _parse_chunk_components(raw_chunk, preferred_name=None, grams_per_piece=None)
    if parsed is None:
        return None
    return {
        "name": parsed["name"],
        "amount_text": parsed["amount_text"],
        "grams": parsed["grams"],
        "required": True,
    }


def _parse_chunk_components(
    raw_chunk: str,
    *,
    preferred_name: Optional[str],
    grams_per_piece: Optional[float],
) -> Optional[Dict[str, Any]]:
    chunk = BULLET_PREFIX_RE.sub("", str(raw_chunk or "").strip())
    if not chunk:
        return None

    if _looks_like_header_line(normalize_text(chunk)):
        return None

    working_chunk, measurement_text, grams = _extract_measurement_from_chunk(chunk)
    amount_text, name_chunk = _extract_amount_text(working_chunk)

    if not amount_text and measurement_text:
        amount_text = measurement_text

    if grams is None and amount_text:
        piece_count = _piece_count_from_amount_text(amount_text)
        if piece_count is not None:
            grams = _grams_from_piece_count(piece_count, grams_per_piece)

    cleaned_name = preferred_name or _clean_name(name_chunk)
    if not cleaned_name:
        return None

    return {
        "name": cleaned_name,
        "amount_text": amount_text,
        "grams": grams,
    }


def _extract_measurement_from_chunk(chunk: str) -> Tuple[str, Optional[str], Optional[float]]:
    paren_matches = list(PAREN_MEASUREMENT_RE.finditer(chunk))
    if paren_matches:
        match = paren_matches[-1]
        measurement_text = match.group(0).strip()[1:-1].strip()
        grams = _measurement_to_grams(match.group(1), match.group(2))
        working_chunk = (chunk[:match.start()] + " " + chunk[match.end():]).strip()
        return _collapse_spaces(working_chunk), measurement_text, grams

    inline_matches = list(INLINE_MEASUREMENT_RE.finditer(chunk))
    if inline_matches:
        match = inline_matches[-1]
        measurement_text = match.group(0).strip()
        grams = _measurement_to_grams(match.group(1), match.group(2))
        working_chunk = (chunk[:match.start()] + " " + chunk[match.end():]).strip()
        return _collapse_spaces(working_chunk), measurement_text, grams

    return _collapse_spaces(chunk), None, None


def _extract_amount_text(chunk: str) -> Tuple[Optional[str], str]:
    match = AMOUNT_TAIL_RE.search(chunk)
    if not match:
        return None, chunk

    candidate = match.group("amount").strip()
    if not _looks_like_amount_text(candidate):
        return None, chunk

    name_chunk = chunk[:match.start()].strip()
    return candidate, name_chunk


def _looks_like_amount_text(candidate: str) -> bool:
    normalized_tokens = [normalize_text(token) for token in candidate.split()]
    if len(normalized_tokens) < 2:
        return False
    return any(token in AMOUNT_UNIT_KEYWORDS for token in normalized_tokens[1:])


def _clean_name(chunk: str) -> Optional[str]:
    cleaned = NOISE_PREFIX_RE.sub("", chunk).strip()
    cleaned = re.sub(r"[\(\)\[\]\{\},;:]", " ", cleaned)
    cleaned = _collapse_spaces(cleaned)

    tokens: List[str] = []
    for token in cleaned.split():
        stripped = token.strip(" .:-–—_/\\")
        normalized = normalize_text(stripped)
        if not stripped or not normalized:
            continue
        if stripped in UNICODE_FRACTIONS:
            continue
        if any(char.isdigit() for char in stripped):
            continue
        if normalized in AMOUNT_UNIT_KEYWORDS or normalized in AMOUNT_DESCRIPTOR_WORDS:
            continue
        if normalized in NON_INGREDIENT_WORDS:
            continue
        tokens.append(stripped)

    final_name = _collapse_spaces(" ".join(tokens)).strip(" .:-")
    return final_name or None


def _piece_count_from_amount_text(amount_text: str) -> Optional[float]:
    normalized_amount = normalize_text(amount_text)
    tokens = normalized_amount.split()
    if len(tokens) < 2:
        return None
    if not any(token in PIECE_UNITS for token in tokens[1:]):
        return None
    return _parse_numeric_value(tokens[0])


def _extract_measurements(
    normalized_source: str,
    start: int,
    end: int,
    *,
    grams_per_piece: Optional[float],
) -> Tuple[Optional[str], Optional[float]]:
    before = normalized_source[max(0, start - 28):start]
    after = normalized_source[end:min(len(normalized_source), end + 28)]

    before_measurement = _last_measurement(before)
    after_measurement = _first_measurement(after)
    chosen = _closest_measurement(before_measurement, after_measurement)
    if chosen is not None:
        amount_text, grams = _measurement_to_fields(chosen[0], chosen[1], grams_per_piece)
        return amount_text, grams

    before_count = _last_plain_count(before)
    if before_count is not None:
        amount_text = f"{_format_number(before_count)} pcs"
        grams = _grams_from_piece_count(before_count, grams_per_piece)
        return amount_text, grams

    after_count = _first_plain_count(after)
    if after_count is not None:
        amount_text = f"{_format_number(after_count)} pcs"
        grams = _grams_from_piece_count(after_count, grams_per_piece)
        return amount_text, grams

    return None, None


def _last_measurement(text: str) -> Optional[Tuple[float, str, int]]:
    matches = list(MEASUREMENT_RE.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    return _measurement_tuple(match.group(1), match.group(2), len(text) - match.end())


def _first_measurement(text: str) -> Optional[Tuple[float, str, int]]:
    match = MEASUREMENT_RE.search(text)
    if not match:
        return None
    return _measurement_tuple(match.group(1), match.group(2), match.start())


def _measurement_tuple(raw_value: str, raw_unit: str, distance: int) -> Tuple[float, str, int]:
    value = _parse_numeric_value(raw_value) or 0.0
    unit = raw_unit.lower().replace(".", "")
    return value, unit, distance


def _closest_measurement(
    before_measurement: Optional[Tuple[float, str, int]],
    after_measurement: Optional[Tuple[float, str, int]],
) -> Optional[Tuple[float, str]]:
    candidates = [candidate for candidate in (before_measurement, after_measurement) if candidate is not None]
    if not candidates:
        return None
    value, unit, _distance = min(candidates, key=lambda item: item[2])
    return value, unit


def _measurement_to_fields(
    value: float,
    unit: str,
    grams_per_piece: Optional[float],
) -> Tuple[Optional[str], Optional[float]]:
    if unit == "kg":
        return f"{_format_number(value)} kg", round(value * 1000.0, 2)
    if unit == "g":
        return f"{_format_number(value)} g", round(value, 2)
    if unit == "l":
        return f"{_format_number(value)} l", None
    if unit == "ml":
        return f"{_format_number(value)} ml", None

    amount_text = f"{_format_number(value)} pcs"
    grams = _grams_from_piece_count(value, grams_per_piece)
    return amount_text, grams


def _measurement_to_grams(raw_value: str, raw_unit: str) -> Optional[float]:
    value = _parse_numeric_value(raw_value)
    if value is None:
        return None
    unit = raw_unit.lower()
    if unit == "kg":
        return round(value * 1000.0, 2)
    if unit == "g":
        return round(value, 2)
    return None


def _last_plain_count(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:[.,]\d+)?|\d+/\d+)\s*$", text)
    if not match:
        return None
    return _parse_numeric_value(match.group(1))


def _first_plain_count(text: str) -> Optional[float]:
    match = LEADING_COUNT_RE.search(text)
    if not match:
        return None
    return _parse_numeric_value(match.group(1))


def _grams_from_piece_count(piece_count: Optional[float], grams_per_piece: Optional[float]) -> Optional[float]:
    if piece_count is None or grams_per_piece is None or piece_count <= 0:
        return None
    return round(piece_count * float(grams_per_piece), 2)


def _parse_numeric_value(raw_value: str) -> Optional[float]:
    text = normalize_text(str(raw_value or ""))
    if not text:
        return None
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            return float(numerator) / denominator_value
        except ValueError:
            return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")
