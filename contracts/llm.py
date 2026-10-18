"""Synthetix shared LLM wrapper v1.0. Any OpenAI-compatible endpoint, set by env vars.
System prompts sent through call_json must mention JSON."""
from __future__ import annotations

import json
import os
import time

from openai import OpenAI

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
    return _client


def call_json(system: str, user: str, timeout: float = 60.0) -> tuple[dict, dict]:
    """One model call that must return a JSON object. Returns (data, usage).
    Raises on timeout, API error or invalid JSON; the caller decides whether to retry."""
    kwargs = {}
    if os.environ.get("LLM_JSON_MODE", "1") == "1":
        kwargs["response_format"] = {"type": "json_object"}
    started = time.time()
    resp = _get_client().chat.completions.create(
        model=os.environ["LLM_MODEL"],
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=float(os.environ.get("LLM_TEMPERATURE", "0.7")),
        timeout=timeout,
        **kwargs,
    )
    usage = {
        "input_tokens": (resp.usage.prompt_tokens if resp.usage else 0) or 0,
        "output_tokens": (resp.usage.completion_tokens if resp.usage else 0) or 0,
        "seconds": time.time() - started,
    }
    data = json.loads(resp.choices[0].message.content or "")
    if not isinstance(data, dict):
        raise ValueError("model did not return a JSON object")
    return data, usage


def cost_hkd(input_tokens: int, output_tokens: int) -> float | None:
    """None means pricing is unknown. Never treat unknown cost as zero."""
    p_in = os.environ.get("LLM_PRICE_IN_HKD_PER_1M")
    p_out = os.environ.get("LLM_PRICE_OUT_HKD_PER_1M")
    if not p_in or not p_out:
        return None
    return input_tokens / 1e6 * float(p_in) + output_tokens / 1e6 * float(p_out)
