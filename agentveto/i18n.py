"""Tiny i18n for decision reasons.

We are not building a localization framework. We just need policy authors
to be able to write one reason in English and one in Chinese and have the
right one picked at runtime. Anything more is over-engineering for the
single maintainer's product.

Lookup order:

1. the `AGENTVETO_LANG` environment variable (e.g. "en", "zh")
2. the first two letters of `LANG` (e.g. "zh_CN.UTF-8" -> "zh")
3. "en"
"""
from __future__ import annotations

import os

DEFAULT_LANG = "en"


def current_lang() -> str:
    forced = os.environ.get("AGENTVETO_LANG", "").strip()
    if forced:
        return forced[:2].lower()
    lang = os.environ.get("LANG", "")
    if lang:
        return lang[:2].lower()
    return DEFAULT_LANG


def localize(reason: object, lang: str | None = None) -> str:
    """Pick the best text for `reason`.

    `reason` may be:
    - a plain str  -> returned as-is
    - a dict {lang: text} -> picks the first matching key (exact, then prefix)
    - anything else -> str(reason)
    """
    if isinstance(reason, str):
        return reason
    if not isinstance(reason, dict):
        return str(reason)
    want = (lang or current_lang())[:2].lower()
    if want in reason and isinstance(reason[want], str):
        return reason[want]
    # fall back by language family
    for k, v in reason.items():
        if isinstance(k, str) and k[:2].lower() == want and isinstance(v, str):
            return v
    if DEFAULT_LANG in reason and isinstance(reason[DEFAULT_LANG], str):
        return reason[DEFAULT_LANG]
    # last resort: any string value
    for v in reason.values():
        if isinstance(v, str):
            return v
    return str(reason)