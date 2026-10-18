"""Model accounting hooks; worker sinks persist each attempted call immediately."""
from __future__ import annotations

from contextlib import nullcontext
from contextvars import ContextVar
import os
import math
import threading
import time
from typing import Callable
from urllib.parse import urlsplit

from contracts import llm

usage_sink: ContextVar[Callable[[dict], None] | None] = ContextVar("usage_sink", default=None)
_local_lock = threading.Lock()


def empty_usage() -> dict:
    return {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0,
            "seconds": 0.0, "cost_hkd": llm.cost_hkd(0, 0)}


def merge_usage(total: dict, delta: dict) -> None:
    for key in ("llm_calls", "input_tokens", "output_tokens", "seconds"):
        total[key] += delta.get(key, 0)
    a, b = total.get("cost_hkd"), delta.get("cost_hkd")
    total["cost_hkd"] = None if a is None or b is None else a + b


class ModelCallError(RuntimeError):
    """Sanitized provider failure; never stores prompts or provider response bodies."""


def call_model(system: str, user: str, usage: dict) -> dict:
    started = time.monotonic()
    local = urlsplit(os.environ.get("LLM_BASE_URL", "")).hostname in {"localhost", "127.0.0.1", "::1"}
    delta = empty_usage()
    delta["llm_calls"] = 1
    sink = usage_sink.get()
    call_started = False
    try:
        # Local inference has one slot. Queue here rather than timing out at the server.
        with _local_lock if local else nullcontext():
            if sink is not None:
                sink({"phase": "start"})
                call_started = True
            timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "180" if local else "60"))
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("LLM_TIMEOUT_SECONDS must be finite and positive")
            data, raw = llm.call_json(system, user, timeout=timeout)
        for key in ("input_tokens", "output_tokens"):
            delta[key] = int(raw.get(key, 0))
        delta["cost_hkd"] = llm.cost_hkd(delta["input_tokens"], delta["output_tokens"])
    except Exception as exc:
        delta["cost_hkd"] = None  # The wrapper cannot recover billed usage on a failed call.
        raise ModelCallError(type(exc).__name__) from None
    finally:
        delta["seconds"] = time.monotonic() - started
        merge_usage(usage, delta)
        if sink is not None:
            sink({**delta, "phase": "finish", "llm_calls": 0} if call_started else delta)
    return data
