#!/usr/bin/env python3
"""Admin API-key client for bounded controller diagnostics; standard library only."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("discover", "start", "status", "report", "stop"))
    parser.add_argument("--capture-id", type=UUID)
    parser.add_argument("--level", choices=("light", "cpu", "allocations", "full"), default="cpu")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--target", action="append")
    args = parser.parse_args()
    base = os.environ.get("COGNIS_URL", "").rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        parser.error("COGNIS_URL must be an HTTPS origin without credentials or query")
    key = os.environ.get("COGNIS_ADMIN_API_KEY", "")
    if not key:
        parser.error("Inject COGNIS_ADMIN_API_KEY from your credential store")
    if args.action != "discover" and not args.capture_id:
        parser.error("--capture-id is required; reuse it when retrying an uncertain start")
    path = "/api/v1/system/profiling"
    body = None
    method = "GET"
    if args.action == "start":
        path += "/captures"
        method = "POST"
        body = json.dumps(
            {
                "capture_id": str(args.capture_id),
                "targets": args.target,
                "options": {"level": args.level, "duration_seconds": args.duration},
            }
        ).encode()
    elif args.action != "discover":
        path += f"/captures/{args.capture_id}"
        if args.action in ("report", "stop"):
            path += "/" + args.action
        if args.action == "stop":
            method = "POST"
    request = urllib.request.Request(
        base + path,
        data=body,
        method=method,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        print(json.dumps({"error": "api_request_failed", "status": exc.code}), file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError):
        print("Request outcome uncertain; retry with the same capture ID.", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
