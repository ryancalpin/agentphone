from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import adbctl

AGENTPHONE_HOME = Path(__file__).resolve().parents[1]
STATE_DIR = AGENTPHONE_HOME / "state"
APPROVAL_FILE = STATE_DIR / "approvals.json"
SHOT_DIR = STATE_DIR / "approval_screenshots"

STATE_DIR.mkdir(parents=True, exist_ok=True)
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[dict[str, Any]]:
    if not APPROVAL_FILE.exists():
        return []
    try:
        return json.loads(APPROVAL_FILE.read_text())
    except Exception:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    tmp = APPROVAL_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, indent=2, sort_keys=True))
    tmp.replace(APPROVAL_FILE)


def list_approvals() -> list[dict[str, Any]]:
    return sorted(_load(), key=lambda x: x.get("created_at", ""), reverse=True)


def get_approval(approval_id: str) -> dict[str, Any] | None:
    for item in _load():
        if item.get("id") == approval_id:
            return item
    return None


def create_approval(app: str, action: str, message: str, risk: str = "medium") -> dict[str, Any]:
    approval_id = str(uuid.uuid4())
    screenshot_path = SHOT_DIR / f"{approval_id}.png"
    try:
        screenshot_path.write_bytes(adbctl.screenshot_png())
        screenshot_ok = True
    except Exception as exc:
        screenshot_path.write_bytes(b"")
        screenshot_ok = False
        message = f"{message}\n\nScreenshot capture failed: {exc}"
    item = {
        "id": approval_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "status": "pending",
        "risk": risk,
        "app": app,
        "action": action,
        "message": message,
        "screenshot_ok": screenshot_ok,
        "screenshot": f"/api/approvals/{approval_id}/screenshot.png",
        "live_url": "/",
    }
    items = _load()
    items.append(item)
    _save(items)
    return item


def update_status(approval_id: str, status: str) -> dict[str, Any] | None:
    items = _load()
    for item in items:
        if item.get("id") == approval_id:
            item["status"] = status
            item["updated_at"] = now_iso()
            _save(items)
            return item
    return None


def screenshot_path(approval_id: str) -> Path:
    return SHOT_DIR / f"{approval_id}.png"


def seed_if_empty() -> None:
    if not APPROVAL_FILE.exists():
        _save([])
