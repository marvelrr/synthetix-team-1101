"""Measure only approved sizes (1, 10, 50); stop if no user completes a size."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime
import errno
from functools import partial
from http.client import HTTPConnection
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from contracts import db
from contracts.models import AudienceSpec, RunConfig, Segment, SyntheticUser, TaskSpec, Usage
from engine.api import start_run

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "engine/RUNS_LOG.md"


def record_run(run_id: str, wall_seconds: float | None = None, note: str = "") -> None:
    with closing(db.connect()) as conn:
        run = db.get_run(conn, run_id)
        if run is None:
            raise ValueError("unknown run_id")
        counts = db.status_counts(conn, run_id)
        assert sum(counts.values()) == run["config"].user_count
        usages = db.load_records(conn, "usage", Usage, run_id)
    metadata_file = Path("data/logs") / f"{run_id}.metadata.json"
    metadata = json.loads(metadata_file.read_text()) if metadata_file.exists() else {}
    model = metadata.get("model") or os.environ.get("LLM_MODEL", "unknown")
    wall = wall_seconds if wall_seconds is not None else run["updated_at"] - run["created_at"]
    avg = sum(u.seconds for u in usages) / len(usages) if usages else None
    cost = None if not usages or any(u.cost_hkd is None for u in usages) else sum(u.cost_hkd for u in usages)
    date = datetime.fromtimestamp(run["created_at"], ZoneInfo("Asia/Hong_Kong")).isoformat(timespec="seconds")
    row = (f"| {date} | {run_id} | {run['config'].mode.value} / {run['config'].product_version} | {model} | {run['config'].max_concurrency} | "
           f"{run['config'].user_count} | {counts['completed']} | {counts['failed']} | {counts['cancelled']} | "
           f"{wall:.3f} | {f'{avg:.3f}' if avg is not None else 'unknown'} | "
           f"{sum(u.input_tokens for u in usages)} / {sum(u.output_tokens for u in usages)} | "
           f"{f'{cost:.6f}' if cost is not None else 'unknown'} |\n")
    if not LOG.exists():
        LOG.write_text("# Measured engine runs\n\nSynthetic simulation — not real user research.\n\n"
                       "Times are measured, not capacity promises. Average seconds per user includes recorded attempts. "
                       "Tokens are returned usage only; failed provider calls may have unavailable token usage.\n\n"
                       "| Date (HKT) | Run | Mode / version | Model | Concurrency | Requested | Completed | Failed | Cancelled | Wall s | Avg s/user | Input / output tokens | Cost HKD |\n"
                       "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n\n## Notes\n", encoding="utf-8")
    if run_id not in LOG.read_text():
        table, _, notes = LOG.read_text().partition("\n## Notes\n")
        if note:
            notes = notes.rstrip() + f"\n\n- {run_id}: {note}\n"
        LOG.write_text(table.rstrip() + "\n" + row + "\n## Notes\n" + notes, encoding="utf-8")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=int, nargs="+", choices=[1, 10, 50], default=[1, 10, 50])
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--budget-hkd", type=float)
    parser.add_argument("--browser-host", choices=["127.0.0.1", "localhost", "host.docker.internal"],
                        help="Hostname the browser uses to reach the local test server")
    args = parser.parse_args()
    if args.counts != sorted(set(args.counts)):
        parser.error("sizes must be unique and in increasing order")
    demo = ROOT / "demo_product/v1"
    using_demo = (demo / "index.html").is_file() and (ROOT / "demo_product/tasks.json").is_file()
    browser_host = args.browser_host or ("localhost" if using_demo else "127.0.0.1")
    directory = demo if using_demo else ROOT / "engine/tests/stub_site"
    port = 8101 if using_demo else 0
    server = thread = None
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), partial(QuietHandler, directory=str(directory)))
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
    except OSError as exc:
        if not using_demo or exc.errno != errno.EADDRINUSE:
            raise
        # The local launcher may already serve this exact static demo. Reuse it
        # without taking ownership; never measure an unrelated service on 8101.
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("GET", "/index.html")
            response = connection.getresponse()
            if response.status != 200 or response.read(250_001) != (directory / "index.html").read_bytes():
                raise RuntimeError("port 8101 is occupied by a different product; refusing to measure it")
        finally:
            connection.close()
    if using_demo:
        tasks = [TaskSpec.model_validate(t) for t in json.loads((ROOT / "demo_product/tasks.json").read_text())]
    else:
        tasks = [TaskSpec(task_id="T1", instruction="Find the monthly price of the Basic plan", success_check="text_visible:HK$268 per month"),
                 TaskSpec(task_id="T2", instruction="Check whether the product delivers to Kwun Tong", success_check="text_visible:Kwun Tong"),
                 TaskSpec(task_id="T3", instruction="Start the free trial using the test details provided", success_check="url_contains:/welcome.html")]
    audience = AudienceSpec(spec_version="engine-benchmark-1", description="Authored benchmark profiles, not representative market data", segments=[
        Segment(name="Household", weight=1, attributes={"tech comfort": ["moderate", "high"], "price sensitivity": ["moderate", "high"]},
                authored_assumptions=["All benchmark profile traits are authored assumptions, not population facts."])
    ])
    try:
        for count in args.counts:
            config = RunConfig(product_name="RefillHK" if using_demo else "Refill testing stub", product_version="v1" if using_demo else "stub-1",
                               mode="interactive", product_url=f"http://{browser_host}:{port}",
                               value_proposition="Household cleaning-product refills in reusable bottles", objective="Measure the actual engine path",
                               audience=audience, user_count=count, tasks=tasks, max_concurrency=args.concurrency, budget_hkd=args.budget_hkd)
            started = time.monotonic()
            run_id = start_run(config)
            print(f"Started {run_id}: {count} users, concurrency {args.concurrency}, {'demo v1' if using_demo else 'test stub'}", flush=True)
            while True:
                with closing(db.connect()) as conn:
                    run = db.get_run(conn, run_id)
                    counts = db.status_counts(conn, run_id)
                if run["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(1)
            wall = time.monotonic() - started
            note = "Demo v1 interaction." if using_demo else "Static engine test stub; this is not the demo product or a capacity claim."
            if not counts["completed"]:
                note += " No user completed. Any startup-failure timings measure bookkeeping, not browser task performance. Larger sizes were not attempted."
            record_run(run_id, wall, note)
            print(f"Settled {run_id}: {counts}; wall_seconds={wall:.3f}", flush=True)
            if not counts["completed"] or run["status"] != "completed":
                return 1
        return 0
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
