"""Required live provider smoke test. Run from the repo root: python -m engine.smoke."""
from __future__ import annotations

import json
import sys

from dotenv import load_dotenv

from contracts import llm


def main() -> int:
    load_dotenv()
    try:
        data, usage = llm.call_json(
            system="Return only a JSON object for a connectivity smoke test.",
            user='Return {"ok": true}.',
        )
    except KeyError as exc:
        print(f"Smoke test failed: missing environment variable {exc.args[0]}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Provider exception messages can contain request content or credentials.
        print(f"Smoke test failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps({"json": data, "usage": usage}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
