#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:3008"
PUBLIC_BASE = os.environ.get("AGENTPHONE_PUBLIC_URL", "http://127.0.0.1:3008")


def request_json(method: str, path: str, data: dict | None = None) -> dict:
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an AgentPhone approval and wait for user decision.")
    parser.add_argument("--app", default="AgentPhone")
    parser.add_argument("--risk", default="medium")
    parser.add_argument("--action", required=True)
    parser.add_argument("--message", default="Approval requested.")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    created = request_json("POST", "/api/approvals", {
        "app": args.app,
        "risk": args.risk,
        "action": args.action,
        "message": args.message,
    })
    approval = created["approval"]
    approval_id = approval["id"]
    url = f"{PUBLIC_BASE}/approvals/{approval_id}"
    print(f"Approval requested: {url}", flush=True)

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        current = request_json("GET", f"/api/approvals/{approval_id}")["approval"]
        status = current["status"]
        if status == "approved":
            print("APPROVED", flush=True)
            return 0
        if status == "denied":
            print("DENIED", flush=True)
            return 2
        if status == "editing":
            print("User is editing/taking control...", flush=True)
        time.sleep(3)

    print("EXPIRED", flush=True)
    return 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as exc:
        print(f"AgentPhone approval helper failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
