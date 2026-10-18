from contextlib import closing
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import threading

import pytest
from dotenv import load_dotenv

from contracts import db, llm
from contracts.models import AudienceSpec, Segment

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    original = db.connect
    path = tmp_path / "data" / "synthetix.db"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db, "connect", lambda: original(path))
    monkeypatch.setenv("LLM_PRICE_IN_HKD_PER_1M", "")
    monkeypatch.setenv("LLM_PRICE_OUT_HKD_PER_1M", "")
    monkeypatch.setenv("SAVE_SCREENSHOTS", "0")
    # Worker unit doubles must not inherit a real development browser endpoint.
    # Real browser tests deliberately use the separate SYNTHETIX_TEST_CDP_URL.
    monkeypatch.setenv("SYNTHETIX_CDP_URL", "")
    def forbidden(*args, **kwargs):
        raise AssertionError("Live model calls are forbidden in pytest; monkeypatch contracts.llm.call_json")
    monkeypatch.setattr(llm, "call_json", forbidden)
    yield
    # Check every run in every test, including launch errors and unsettled runs.
    with closing(db.connect()) as conn:
        for run in db.list_runs(conn):
            assert sum(db.status_counts(conn, run["run_id"]).values()) == run["config"].user_count


@pytest.fixture
def audience():
    return AudienceSpec(spec_version="test-1", description="Authored test fixtures", segments=[
        Segment(name="a", weight=2, attributes={"age": ["18–24", "25–34"], "comfort": ["high", "low"]},
                sourced_facts=["A cited fixture fact"], authored_assumptions=["An authored fixture assumption"]),
        Segment(name="b", weight=1, attributes={"age": ["35–44"]}, languages=["en", "zh-HK"]),
    ])


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def stub_url():
    directory = Path(__file__).parent / "stub_site"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = os.environ.get("SYNTHETIX_TEST_SITE_HOST", "127.0.0.1")
    yield f"http://{host}:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
