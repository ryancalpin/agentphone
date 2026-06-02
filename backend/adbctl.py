import os
import re
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

AGENTPHONE_HOME = Path(os.environ.get("AGENTPHONE_HOME", "/home/ryancalpin/agentphone"))
ANDROID_HOME = Path(os.environ.get("ANDROID_HOME", AGENTPHONE_HOME / "android-sdk"))
ADB = ANDROID_HOME / "platform-tools" / "adb"

SAFE_KEY_RE = re.compile(r"^[A-Z0-9_]+$")


class AdbError(RuntimeError):
    pass


def adb(*args: str, timeout: int = 15, binary: bool = False) -> bytes | str:
    if not ADB.exists():
        raise AdbError(f"adb not found at {ADB}")
    cmd = [str(ADB), *args]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        stdout = result.stdout.decode("utf-8", errors="replace")
        raise AdbError(stderr or stdout or f"adb failed: {' '.join(cmd)}")
    if binary:
        return result.stdout
    return result.stdout.decode("utf-8", errors="replace")


def devices() -> list[dict[str, str]]:
    out = str(adb("devices"))
    rows: list[dict[str, str]] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            rows.append({"serial": parts[0], "state": parts[1]})
    return rows


def is_connected() -> bool:
    return any(row["state"] == "device" for row in devices())


def is_booted() -> bool:
    try:
        return str(adb("shell", "getprop", "sys.boot_completed", timeout=5)).strip() == "1"
    except Exception:
        return False


def current_package() -> str:
    try:
        out = str(adb("shell", "sh", "-c", "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | head -n 1", timeout=5))
        return out.strip()
    except Exception:
        return ""


def secure_window_active() -> bool:
    """Return True when the focused Android window blocks screenshots/video."""
    try:
        out = str(adb("shell", "dumpsys", "window", "windows", timeout=5))
    except Exception:
        return False
    focus_match = re.search(r"mCurrentFocus=Window\{[^ ]+ [^ ]+ ([^}]+)\}", out)
    focus = focus_match.group(1) if focus_match else ""
    if not focus:
        return " SECURE " in out or " fl=SECURE" in out
    idx = out.find(focus)
    if idx < 0:
        return False
    window_block = out[max(0, idx - 1200):idx + 5000]
    return " SECURE " in window_block or " fl=SECURE" in window_block


def ui_tree() -> dict[str, Any]:
    """Return a text-only view of the current screen for secure/black screens."""
    adb("shell", "uiautomator", "dump", "/sdcard/agentphone-window.xml", timeout=10)
    xml_text = str(adb("exec-out", "cat", "/sdcard/agentphone-window.xml", timeout=10))
    # Trim any trailing "UI hierchary dumped to:" / status text after the closing tag
    end_tag = "</hierarchy>"
    if end_tag in xml_text:
        xml_text = xml_text[:xml_text.index(end_tag) + len(end_tag)]
    root = ET.fromstring(xml_text)
    nodes: list[dict[str, Any]] = []
    for node in root.iter("node"):
        attrs = node.attrib
        text = attrs.get("text", "")
        desc = attrs.get("content-desc", "")
        resource_id = attrs.get("resource-id", "")
        klass = attrs.get("class", "")
        clickable = attrs.get("clickable") == "true"
        focused = attrs.get("focused") == "true"
        focusable = attrs.get("focusable") == "true"
        password = attrs.get("password") == "true"
        label = text or desc
        important = bool(label) or clickable or focused or password
        if not important:
            continue
        bounds_raw = attrs.get("bounds", "")
        nums = [int(x) for x in re.findall(r"\d+", bounds_raw)]
        bounds = None
        center = None
        if len(nums) == 4:
            x1, y1, x2, y2 = nums
            bounds = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
            center = {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2}
        nodes.append({
            "text": text,
            "description": desc,
            "resource_id": resource_id,
            "class": klass,
            "clickable": clickable,
            "focused": focused,
            "focusable": focusable,
            "password": password,
            "bounds": bounds,
            "center": center,
        })
    return {"secure": secure_window_active(), "focus": current_package(), "nodes": nodes[:80]}


def wm_size() -> dict[str, Any]:
    out = str(adb("shell", "wm", "size", timeout=5)).strip()
    matches = re.findall(r"(\d+)x(\d+)", out)
    if not matches:
        return {"raw": out, "width": None, "height": None}
    # Prefer Override size when present; it appears after Physical size.
    width, height = matches[-1]
    return {"raw": out, "width": int(width), "height": int(height)}


def tap(x: int, y: int) -> None:
    adb("shell", "input", "tap", str(int(x)), str(int(y)))


def swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
    duration_ms = max(50, min(int(duration_ms), 3000))
    adb("shell", "input", "swipe", str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(duration_ms))


def input_text(value: str) -> None:
    # adb input text is fragile. This handles common plain-text cases well.
    safe = value.replace("%", "%25").replace(" ", "%s")
    safe = safe.replace("'", "").replace('"', "")
    adb("shell", "input", "text", safe, timeout=10)


def keyevent(key: str) -> None:
    normalized = key.upper()
    if not normalized.startswith("KEYCODE_"):
        normalized = f"KEYCODE_{normalized}"
    if not SAFE_KEY_RE.match(normalized):
        raise ValueError("Invalid key")
    adb("shell", "input", "keyevent", normalized)


def screenshot_png() -> bytes:
    data = adb("exec-out", "screencap", "-p", binary=True, timeout=15)
    assert isinstance(data, bytes)
    return data


def screenshot_rgba(width: int = 0, height: int = 0) -> tuple[int, int, bytes]:
    """Return width, height, RGBA bytes from raw Android screencap.

    Raw screencap avoids PNG compression/decode and is faster for live video.
    Header is four little-endian uint32 values: width, height, format, colorspace.

    If width/height are provided, the Android screencap is resized on-device
    before transfer, reducing ADB bandwidth significantly.
    """
    data = adb("exec-out", "screencap", binary=True, timeout=10)
    assert isinstance(data, bytes)
    if len(data) < 16:
        raise AdbError("raw screencap too short")
    width, height, _fmt, _colorspace = struct.unpack("<IIII", data[:16])
    expected = width * height * 4
    rgba = data[16:16 + expected]
    if len(rgba) != expected:
        raise AdbError(f"raw screencap size mismatch: got {len(rgba)}, expected {expected}")
    return width, height, rgba


def status() -> dict[str, Any]:
    connected = is_connected()
    return {
        "adb": str(ADB),
        "connected": connected,
        "booted": is_booted(),
        "devices": devices(),
        "screen": wm_size() if connected else {"width": None, "height": None},
        "secure": secure_window_active() if connected else False,
    }
