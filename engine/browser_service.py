"""Run a dedicated, loopback-only Chromium service in installed Docker Desktop."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from urllib.request import urlopen

from dotenv import load_dotenv


# Runs only inside the disposable browser container. No project, data, credentials
# or Docker socket is mounted. A TCP relay makes Chromium's loopback CDP reachable
# through the explicitly loopback-bound Docker port, without logging its traffic.
CONTAINER_PROGRAM = r'''
import glob
import select
import shutil
import socket
import socketserver
import subprocess
import threading

paths = glob.glob('/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell')
if not paths:
    paths = glob.glob('/ms-playwright/chromium-*/chrome-linux*/chrome')
if not paths:
    paths = [p for p in [shutil.which('chromium'), shutil.which('chromium-browser')] if p]
if not paths:
    raise SystemExit('Chromium binary missing from browser image')
browser = subprocess.Popen([
    paths[0], '--headless', '--no-sandbox', '--disable-gpu',
    '--disable-background-networking', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9222',
    '--user-data-dir=/tmp/synthetix-chromium', 'about:blank',
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            with socket.create_connection(('127.0.0.1', 9222), timeout=5) as upstream:
                upstream.settimeout(None)
                sockets = [self.request, upstream]
                while True:
                    ready, _, _ = select.select(sockets, [], [], 30)
                    if not ready:
                        if browser.poll() is not None:
                            return
                        continue
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is self.request else self.request).sendall(data)
        except (OSError, ConnectionError):
            return

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    def handle_error(self, request, address):
        pass

with Server(('0.0.0.0', 9223), Relay) as server:
    def watch_browser():
        code = browser.wait()
        print('Chromium stopped; exit code: ' + str(code), flush=True)
        server.shutdown()
    threading.Thread(target=watch_browser, daemon=True).start()
    server.serve_forever()
'''


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=os.environ.get("SYNTHETIX_BROWSER_IMAGE", "synthetix-browser:alpine-3.22"))
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--name", default="synthetix-browser")
    parser.add_argument("--stop", action="store_true", help="Stop this disposable browser service")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be in 1024..65535")
    if args.stop:
        return subprocess.run(["docker", "stop", args.name], check=False).returncode
    command = [
        "docker", "run", "--rm", "--detach", "--init", "--name", args.name,
        "--memory", "1g", "--shm-size", "256m",
        "--publish", f"127.0.0.1:{args.port}:9223",
        "--entrypoint", "python3", args.image, "-u", "-c", CONTAINER_PROGRAM,
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode:
        print(result.stderr.strip())
        return result.returncode
    endpoint = f"http://127.0.0.1:{args.port}"
    for _ in range(60):
        try:
            with urlopen(endpoint + "/json/version", timeout=2) as response:
                version = json.load(response)
            print(json.dumps({"endpoint": endpoint, "browser": version.get("Browser"),
                              "container": args.name, "image": args.image}))
            print(f"Set SYNTHETIX_CDP_URL={endpoint} for workers.")
            print(f"Set SYNTHETIX_TEST_CDP_URL={endpoint} and SYNTHETIX_TEST_SITE_HOST=host.docker.internal for tests.")
            return 0
        except (OSError, ValueError):
            time.sleep(0.5)
    print(f"Browser service did not become ready; inspect container {args.name}.")
    subprocess.run(["docker", "stop", args.name], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
