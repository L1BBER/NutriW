from __future__ import annotations

import re
import unicodedata

SPECIAL_LATIN_TO_ASCII = {
    "ą": "a",
    "ć": "c",
    "ę": "e",
    "ł": "l",
    "ń": "n",
    "ó": "o",
    "ś": "s",
    "ź": "z",
    "ż": "z",
    "Ą": "A",
    "Ć": "C",
    "Ę": "E",
    "Ł": "L",
    "Ń": "N",
    "Ó": "O",
    "Ś": "S",
    "Ź": "Z",
    "Ż": "Z",
}

UNICODE_FRACTIONS = {
    "½": " 1/2 ",
    "⅓": " 1/3 ",
    "⅔": " 2/3 ",
    "¼": " 1/4 ",
    "¾": " 3/4 ",
}

CYRILLIC_TO_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "h",
    "ґ": "g",
    "д": "d",
    "е": "e",
    "є": "ye",
    "ж": "zh",
    "з": "z",
    "и": "y",
    "і": "i",
    "ї": "yi",
    "й": "i",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ь": "",
    "ю": "yu",
    "я": "ya",
    "ъ": "",
    "ы": "y",
    "э": "e",
}


def transliterate_cyrillic(value: str) -> str:
    return "".join(CYRILLIC_TO_LATIN.get(char, CYRILLIC_TO_LATIN.get(char.casefold(), char)) for char in value)


def replace_special_latin_chars(value: str) -> str:
    return "".join(SPECIAL_LATIN_TO_ASCII.get(char, char) for char in value)


def replace_unicode_fractions(value: str) -> str:
    return "".join(UNICODE_FRACTIONS.get(char, char) for char in value)


def normalize_text(value: str) -> str:
    normalized = replace_unicode_fractions(value or "")
    normalized = replace_special_latin_chars(normalized)
    normalized = unicodedata.normalize("NFKD", normalized)
    transliterated = transliterate_cyrillic(normalized)
    ascii_value = unicodedata.normalize("NFKD", transliterated).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_value).strip().casefold()


def compact_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value))
