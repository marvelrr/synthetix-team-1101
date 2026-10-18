"""Bounded literal page evidence extracted in code, never inferred by a model."""
from __future__ import annotations

import json
import re

PRICE = re.compile(r"(?:HK\$|HKD|US\$|USD|GBP|EUR|\$|£|€)\s*\d[\d,]*(?:\.\d{1,2})?(?:\s*(?:per\s+(?:month|year|week)|/\s*(?:month|year|week|mo)))?", re.I)
PAGE_TEXT_EXCERPT_LIMIT = 1200
CONTROL_EVIDENCE_LIMIT = 12


def page_evidence(url: str, title: str, visible_text: str, elements: list[dict]) -> dict:
    """Return observed data for a DB trace, never a log or model-authored summary.

    Callers must continue treating every stored string as untrusted page data.
    The excerpt is a literal prefix; it is not evidence that omitted content
    was absent. No field values or select-option values are copied here.
    """
    controls = []
    for element in elements[:CONTROL_EVIDENCE_LIMIT]:
        label = next((element.get(key) for key in ("label", "text", "placeholder")
                      if isinstance(element.get(key), str) and element[key]), "")
        control = {"element": element["element"], "label": label[:60]}
        if isinstance(element.get("tag"), str):
            control["tag"] = element["tag"][:20]
        controls.append(control)
    return {"url": url[:2048], "title": title[:100],
            "visible_text_excerpt": visible_text[:PAGE_TEXT_EXCERPT_LIMIT],
            "visible_text_chars": len(visible_text),
            "interactive_elements": len(elements), "controls": controls,
            "untrusted_page_data": True, "prices_seen": prices_in(visible_text)}


def prices_in(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0) for m in PRICE.finditer(text)))[:10]


def observed_prices(results) -> list[str]:
    prices = []
    for result in results:
        for step in result.steps:
            try:
                summary = json.loads(step.observation)
            except (ValueError, TypeError):
                continue
            if isinstance(summary, dict):
                for value in summary.get("prices_seen", []):
                    if isinstance(value, str) and PRICE.fullmatch(value):
                        prices.append(value)
    return list(dict.fromkeys(prices))
