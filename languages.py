"""Spoken language and the language a transcript is translated into."""

from __future__ import annotations

LANGUAGES = [
    ("en", "English"),
    ("fr", "French"),
    ("de", "German"),
    ("es", "Spanish"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("ru", "Russian"),
    ("uk", "Ukrainian"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("ar", "Arabic"),
    ("hi", "Hindi"),
    ("tr", "Turkish"),
    ("sv", "Swedish"),
    ("da", "Danish"),
    ("fi", "Finnish"),
    ("cs", "Czech"),
    ("ro", "Romanian"),
    ("el", "Greek"),
    ("hu", "Hungarian"),
]

SPOKEN_LANGUAGES = [("auto", "Detect")] + LANGUAGES
TRANSLATE_LANGUAGES = [("off", "Don't translate")] + LANGUAGES

LANGUAGE_CODES = {code for code, _name in LANGUAGES}

# English-only speech models, and the multilingual model to use instead.
MULTILINGUAL_MODEL = {
    "tiny.en": "tiny",
    "base.en": "base",
    "small.en": "small",
    "medium.en": "medium",
    "distil-large-v3": "large-v3",
}


def language_name(code: str) -> str:
    for candidate, name in SPOKEN_LANGUAGES + TRANSLATE_LANGUAGES:
        if candidate == code:
            return name
    return code


def normalize_spoken(value: object) -> str:
    code = str(value or "en").strip().lower()
    if code == "auto" or code in LANGUAGE_CODES:
        return code
    raise ValueError("Choose a spoken language from the list.")


def normalize_translation(value: object) -> str:
    code = str(value or "").strip().lower()
    if code in ("", "off"):
        return ""
    if code in LANGUAGE_CODES:
        return code
    raise ValueError("Choose a translation language from the list.")


def model_for_language(model: str, language: str) -> str:
    """English-only weights cannot transcribe or detect another language."""
    if language == "en":
        return model
    return MULTILINGUAL_MODEL.get(model, model)
