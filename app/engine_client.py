"""The product layer calls only the shared three-function engine interface."""
from __future__ import annotations

import os

from dotenv import load_dotenv

from contracts.models import RunConfig

load_dotenv()


def _backend():
    if os.environ.get("SYNTHETIX_FAKE_ENGINE", "0") == "1":
        from app import fake_engine
        return fake_engine
    from engine import api
    return api


def start_run(config: RunConfig, is_saved_example: bool = False) -> str:
    return _backend().start_run(config, is_saved_example=is_saved_example)


def cancel_run(run_id: str) -> None:
    _backend().cancel_run(run_id)


def estimate_run(config: RunConfig) -> dict:
    return _backend().estimate_run(config)


__all__ = ["start_run", "cancel_run", "estimate_run"]
