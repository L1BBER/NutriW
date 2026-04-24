from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Sequence

from .text_utils import compact_text, normalize_text

RECIPE_DIETARY_LABELS: List[str] = [
    "Gluten-Free",
    "Lactose-Free",
    "Dairy-Free",
    "High-Protein",
    "Low Sugar",
    "Sugar-Free",
    "Vegan",
    "Vegetarian",
    "Organic",
    "Keto-Friendly",
]

PRODUCT_ONLY_LABELS: List[str] = [
    "UHT",
    "Wolny wybieg",
    "Naturalny",
]

PRODUCT_LABELS: List[str] = [*RECIPE_DIETARY_LABELS, *PRODUCT_ONLY_LABELS]

LABEL_ICONS: Dict[str, str] = {
    "Gluten-Free": "\U0001F33E",
    "Lactose-Free": "\U0001F95B",
    "Dairy-Free": "\U0001F965",
    "High-Protein": "\U0001F4AA",
    "Low Sugar": "\U0001F4C9",
    "Sugar-Free": "\u26D4",
    "Vegan": "\U0001F331",
    "Vegetarian": "\U0001F955",
    "Organic": "\U0001F343",
    "Keto-Friendly": "\U0001F951",
    "UHT": "\U0001F525",
    "Wolny wybieg": "\U0001F414",
    "Naturalny": "\U0001F33F",
}

LABEL_VARIANTS: Dict[str, Sequence[str]] = {
    "Gluten-Free": (
        "gluten free",
        "gluten-free",
        "bez glutenu",
        "bezglutenowe",
        "bezglutenowy",
        "glutenfrei",
        "bez hliutenu",
        "bez gliutenu",
    ),
    "Lactose-Free": (
        "lactose free",
        "lactose-free",
        "without lactose",
        "bez laktozy",
        "bez laktoz",
        "bezlakt",
        "bez laktozi",
        "bezlaktozne",
        "bezlaktoznyi",
    ),
    "Dairy-Free": (
        "dairy free",
        "dairy-free",
        "milk free",
        "without dairy",
        "bez mleka",
        "bez nabialu",
        "bez produktow mlecznych",
        "bez moloka",
        "bez molochnykh",
        "bez molochnykh produktiv",
    ),
    "High-Protein": (
        "high protein",
        "high-protein",
        "protein rich",
        "proteinowe",
        "wysokobialkowe",
        "wysokobialkowy",
        "duzo bialka",
        "duza ilosc bialka",
        "bahato bilka",
        "vysokobilkovyi",
        "vysokobilkova",
    ),
    "Low Sugar": (
        "low sugar",
        "lower sugar",
        "reduced sugar",
        "mniej cukru",
        "niska zawartosc cukru",
        "malo cukru",
        "menshe tsukru",
        "nyzkyi vmist tsukru",
    ),
    "Sugar-Free": (
        "sugar free",
        "sugar-free",
        "without sugar",
        "no sugar",
        "bez cukru",
        "bezcukrowe",
        "bezcukrowy",
        "bez tsukru",
    ),
    "Vegan": (
        "vegan",
        "plant based",
        "plant-based",
        "weganskie",
        "weganski",
        "vehan",
        "vehanskyi",
        "vehanska",
    ),
    "Vegetarian": (
        "vegetarian",
        "vegetarian friendly",
        "wegetarianskie",
        "wegetarianski",
        "vehetarianskyi",
        "vehetarianska",
        "vehetarianske",
    ),
    "Organic": (
        "organic",
        "bio",
        "eko",
        "ecological",
        "ekologiczne",
        "ekologiczny",
        "organiczne",
        "orhanichnyi",
        "orhanichna",
        "ekolohichnyi",
    ),
    "Keto-Friendly": (
        "keto",
        "keto friendly",
        "keto-friendly",
        "ketogenic",
        "ketogeniczny",
        "ketohennyi",
        "ketohenna",
    ),
    "UHT": (
        "uht",
        "ultra high temperature",
        "ultra-high-temperature",
        "ultra heat treated",
        "ultra-heat-treated",
        "ultra pasteurized",
        "ultra-pasteurized",
        "aseptic",
        "long life",
        "long-life",
        "long shelf life",
        "sterilized",
        "sterilised",
        "mleko uht",
        "dlugotrwale",
        "mleko dlugotrwale",
        "ultrapasteryzowane",
        "ultrapasteryzowany",
        "ultrapasteryzovane",
        "ultrapasteryzovana",
        "ultrapasteryzovanyi",
        "dovhotryvale",
        "dovhotryvale moloko",
    ),
    "Wolny wybieg": (
        "wolny wybieg",
        "z wolnego wybiegu",
        "free range",
        "free-range",
        "free roaming",
        "free roaming hens",
        "free range eggs",
        "vilnyi vybih",
        "z vilnoho vybihu",
    ),
    "Naturalny": (
        "natural",
        "naturalny",
        "naturalna",
        "naturalne",
        "nature",
        "naturally made",
        "bez dodatkow",
        "bez konserwantow",
        "natyralnyi",
        "naturalnyi",
    ),
}

RECIPE_LABEL_SET = set(RECIPE_DIETARY_LABELS)
PRODUCT_LABEL_SET = set(PRODUCT_LABELS)
TOKEN_RE = re.compile(r"[a-z0-9]+")


def available_dietary_labels() -> List[str]:
    return list(RECIPE_DIETARY_LABELS)


def available_product_labels() -> List[str]:
    return list(PRODUCT_LABELS)


def available_dietary_label_icons() -> Dict[str, str]:
    return dict(LABEL_ICONS)


def dietary_label_icon(label: str) -> str:
    return LABEL_ICONS.get(str(label or "").strip(), "\U0001F3F7\uFE0F")


def normalize_selected_labels(values: Iterable[Any]) -> List[str]:
    return _normalize_label_values(values, RECIPE_LABEL_SET)


def normalize_product_labels(values: Iterable[Any]) -> List[str]:
    return _normalize_label_values(values, PRODUCT_LABEL_SET)


def _normalize_label_values(values: Iterable[Any], allowed_labels: set[str]) -> List[str]:
    seen: set[str] = set()
    normalized: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text in allowed_labels and text not in seen:
            seen.add(text)
            normalized.append(text)
    return normalized


def infer_dietary_labels(texts: Iterable[str]) -> List[str]:
    ordered: List[str] = []
    normalized_texts = [str(text or "").strip() for text in texts if str(text or "").strip()]

    for label in PRODUCT_LABELS:
        variants = LABEL_VARIANTS.get(label, ())
        if any(_matches_variant(text, variant) for text in normalized_texts for variant in variants):
            ordered.append(label)

    return ordered


def _matches_variant(source_text: str, variant: str) -> bool:
    normalized_source = normalize_text(source_text)
    normalized_variant = normalize_text(variant)
    if not normalized_source or not normalized_variant:
        return False

    compact_source = compact_text(source_text)
    compact_variant = compact_text(variant)
    if not compact_source or not compact_variant:
        return False

    if len(compact_variant) >= 4 and compact_variant in compact_source:
        return True
    if compact_source == compact_variant:
        return True

    ratio = SequenceMatcher(None, compact_source, compact_variant).ratio()
    if ratio >= _ratio_threshold(compact_variant):
        return True

    source_tokens = TOKEN_RE.findall(normalized_source)
    variant_tokens = TOKEN_RE.findall(normalized_variant)
    if not source_tokens or not variant_tokens:
        return False

    token_matches = 0
    for variant_token in variant_tokens:
        if any(SequenceMatcher(None, variant_token, source_token).ratio() >= _ratio_threshold(variant_token) for source_token in source_tokens):
            token_matches += 1

    return token_matches == len(variant_tokens)


def _ratio_threshold(value: str) -> float:
    length = len(value)
    if length <= 3:
        return 1.0
    if length <= 5:
        return 0.88
    if length <= 8:
        return 0.84
    return 0.8
