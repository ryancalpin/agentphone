from __future__ import annotations

import asyncio
import io
import os
import time
from fractions import Fraction
from pathlib import Path
from typing import Any

import av
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.codecs import h264 as h264_codec
from aiortc.rtcrtpsender import RTCRtpSender
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from PIL import Image
from pydantic import BaseModel, Field

import adbctl
import approvals
from scrcpy_native import ScrcpyNativeStream

AGENTPHONE_HOME = Path(os.environ.get("AGENTPHONE_HOME", "/home/ryancalpin/agentphone"))
PWA_DIR = AGENTPHONE_HOME / "pwa"
STATE_DIR = AGENTPHONE_HOME / "state"

app = FastAPI(title="AgentPhone", version="0.2.0")
approvals.seed_if_empty()
# aiortc defaults H.264 to 1 Mbps / max 3 Mbps, which looks blocky for
# a tall remote-phone screen. Use a higher target; resolution/FPS are already
# capped, so this mainly reduces macroblocking and text shimmer.
h264_codec.DEFAULT_BITRATE = int(os.environ.get("AGENTPHONE_H264_BITRATE", "12000000"))
h264_codec.MAX_BITRATE = int(os.environ.get("AGENTPHONE_H264_MAX_BITRATE", "18000000"))
pcs: set[RTCPeerConnection] = set()


class AdbScreenshotVideoTrack(VideoStreamTrack):
    """WebRTC video track backed by the existing reliable ADB screenshot path.

    This gives iPhone Safari a real <video> stream and lower display latency while
    keeping the already-verified ADB control/screenshot/approval stack intact.
    """

    kind = "video"

    def __init__(self, fps: int = 4) -> None:
        super().__init__()
        self.fps = max(1, min(fps, 15))
        self.frame_interval = 1 / self.fps
        self.timestamp = 0
        self.time_base = Fraction(1, 90000)
        self.last_frame: av.VideoFrame | None = None

    async def recv(self) -> av.VideoFrame:
        await asyncio.sleep(self.frame_interval)
        try:
            width, height, rgba = await asyncio.to_thread(adbctl.screenshot_rgba)
            array = np.frombuffer(rgba, dtype=np.uint8).reshape((height, width, 4))
            frame = av.VideoFrame.from_ndarray(array, format="rgba")
            self.last_frame = frame
        except Exception:
            if self.last_frame is None:
                array = np.zeros((1200, 540, 4), dtype=np.uint8)
                frame = av.VideoFrame.from_ndarray(array, format="rgba")
            else:
                frame = self.last_frame.reformat(format="rgba")

        self.timestamp += int(90000 * self.frame_interval)
        frame.pts = self.timestamp
        frame.time_base = self.time_base
        return frame


class NativeScrcpyVideoTrack(VideoStreamTrack):
    """WebRTC track using scrcpy-server's native Android H.264 capture path.

    If the native stream stalls or a secure/protected app closes the stream, this
    falls back to ADB raw screenshots so WebRTC stays alive and the PWA's secure
    text overlay can remain usable.
    """

    kind = "video"

    def __init__(self, fallback_fps: int = 4) -> None:
        super().__init__()
        self.stream = ScrcpyNativeStream()
        self.fallback_interval = 1 / max(1, min(fallback_fps, 15))
        self.timestamp = 0
        self.time_base = Fraction(1, 90000)
        self.last_frame: av.VideoFrame | None = None
        self.source = "scrcpy-native"

    async def recv(self) -> av.VideoFrame:
        frame = await asyncio.to_thread(self.stream.latest_frame, 0.45)
        if frame is None:
            self.source = "adb-fallback"
            await asyncio.sleep(self.fallback_interval)
            try:
                width, height, rgba = await asyncio.to_thread(adbctl.screenshot_rgba)
                array = np.frombuffer(rgba, dtype=np.uint8).reshape((height, width, 4))
                frame = av.VideoFrame.from_ndarray(array, format="rgba")
            except Exception:
                if self.last_frame is None:
                    array = np.zeros((1200, 540, 4), dtype=np.uint8)
                    frame = av.VideoFrame.from_ndarray(array, format="rgba")
                else:
                    frame = self.last_frame.reformat(format="rgba")
        else:
            self.source = "scrcpy-native"

        self.last_frame = frame
        self.timestamp += 3000  # 90kHz / ~30fps; freshness matters more than exact device cadence.
        frame.pts = self.timestamp
        frame.time_base = self.time_base
        return frame

    def stop(self) -> None:
        try:
            self.stream.stop()
        finally:
            super().stop()


class WebRTCOffer(BaseModel):
    sdp: str
    type: str


class TapRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class SwipeRequest(BaseModel):
    x1: int = Field(ge=0)
    y1: int = Field(ge=0)
    x2: int = Field(ge=0)
    y2: int = Field(ge=0)
    duration_ms: int = Field(default=300, ge=50, le=3000)


class TypeRequest(BaseModel):
    text: str = Field(min_length=0, max_length=4000)


class KeyRequest(BaseModel):
    key: str = Field(min_length=1, max_length=64)


class ApprovalCreate(BaseModel):
    app: str = Field(default="AgentPhone", max_length=120)
    action: str = Field(max_length=240)
    message: str = Field(default="Approval requested.", max_length=2000)
    risk: str = Field(default="medium", max_length=40)


def api_ok(data: dict[str, Any] | None = None) -> JSONResponse:
    payload = {"ok": True}
    if data:
        payload.update(data)
    return JSONResponse(payload)


def api_error(exc: Exception, status_code: int = 500) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=status_code)


def serve_index() -> FileResponse:
    path = PWA_DIR / "index.html"
    if not path.exists():
        return HTMLResponse("<h1>AgentPhone</h1><p>PWA not installed yet.</p>")
    return FileResponse(path, media_type="text/html")


@app.get("/")
@app.get("/android")
@app.get("/android/")
@app.get("/approvals")
@app.get("/approvals/{approval_id}")
@app.get("/android/approvals")
@app.get("/android/approvals/{approval_id}")
def index():
    return serve_index()


@app.get("/manifest.webmanifest")
@app.get("/android/manifest.webmanifest")
def manifest():
    return FileResponse(PWA_DIR / "manifest.webmanifest", media_type="application/manifest+json", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/app.js")
@app.get("/android/app.js")
def app_js():
    return FileResponse(PWA_DIR / "app.js", media_type="application/javascript", headers={"Cache-Control": "public, max-age=300"})


@app.get("/styles.css")
@app.get("/android/styles.css")
def styles():
    return FileResponse(PWA_DIR / "styles.css", media_type="text/css", headers={"Cache-Control": "public, max-age=300"})


@app.get("/sw.js")
@app.get("/android/sw.js")
def service_worker():
    return FileResponse(PWA_DIR / "sw.js", media_type="application/javascript")


@app.get("/icon.svg")
@app.get("/android/icon.svg")
def icon():
    return FileResponse(PWA_DIR / "icon.svg", media_type="image/svg+xml")


@app.get("/api/health")
@app.get("/android/api/health")
def health():
    return api_ok({"service": "agentphone"})


@app.get("/api/status")
@app.get("/android/api/status")
def status():
    try:
        data = adbctl.status()
        data["current_focus"] = adbctl.current_package()
        return api_ok(data)
    except Exception as exc:
        return api_error(exc)


@app.get("/api/ui")
@app.get("/android/api/ui")
def ui_tree():
    try:
        return api_ok(adbctl.ui_tree())
    except Exception as exc:
        return api_error(exc)


@app.get("/api/screenshot.png")
@app.get("/android/api/screenshot.png")
def screenshot_png():
    try:
        return Response(content=adbctl.screenshot_png(), media_type="image/png", headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return api_error(exc)


@app.get("/api/stream.mjpeg")
@app.get("/android/api/stream.mjpeg")
def stream_mjpeg():
    def frames():
        while True:
            try:
                png = adbctl.screenshot_png()
                yield (
                    b"--agentphone\r\n"
                    b"Content-Type: image/png\r\n"
                    + f"Content-Length: {len(png)}\r\n\r\n".encode("ascii")
                    + png
                    + b"\r\n"
                )
                time.sleep(0.02)
            except GeneratorExit:
                break
            except Exception:
                time.sleep(0.25)

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=agentphone",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/api/webrtc/offer")
@app.post("/android/api/webrtc/offer")
async def webrtc_offer(req: WebRTCOffer):
    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState in {"failed", "closed", "disconnected"}:
            await pc.close()
            pcs.discard(pc)

    try:
        track = NativeScrcpyVideoTrack(fallback_fps=4)
        stream_source = "scrcpy-native"
    except Exception:
        track = AdbScreenshotVideoTrack(fps=4)
        stream_source = "adb-screenshot"
    pc.addTrack(track)

    try:
        await pc.setRemoteDescription(RTCSessionDescription(sdp=req.sdp, type=req.type))
        # iPhone Safari is happiest with H.264. Keep other codecs as fallback.
        for transceiver in pc.getTransceivers():
            if transceiver.kind != "video":
                continue
            caps = RTCRtpSender.getCapabilities("video")
            h264 = [codec for codec in caps.codecs if codec.mimeType.lower() == "video/h264"]
            others = [codec for codec in caps.codecs if codec.mimeType.lower() != "video/h264"]
            if h264:
                transceiver.setCodecPreferences(h264 + others)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return api_ok({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "source": stream_source})
    except Exception as exc:
        await pc.close()
        pcs.discard(pc)
        return api_error(exc)


@app.get("/api/webrtc/status")
@app.get("/android/api/webrtc/status")
def webrtc_status():
    return api_ok({"connections": len(pcs)})


@app.on_event("shutdown")
async def on_shutdown():
    coros = [pc.close() for pc in pcs]
    if coros:
        await asyncio.gather(*coros, return_exceptions=True)
    pcs.clear()


@app.post("/api/tap")
@app.post("/android/api/tap")
def tap(req: TapRequest):
    try:
        adbctl.tap(req.x, req.y)
        return api_ok()
    except Exception as exc:
        return api_error(exc)


@app.post("/api/swipe")
@app.post("/android/api/swipe")
def swipe(req: SwipeRequest):
    try:
        adbctl.swipe(req.x1, req.y1, req.x2, req.y2, req.duration_ms)
        return api_ok()
    except Exception as exc:
        return api_error(exc)


@app.post("/api/type")
@app.post("/android/api/type")
def type_text(req: TypeRequest):
    try:
        adbctl.input_text(req.text)
        return api_ok()
    except Exception as exc:
        return api_error(exc)


@app.post("/api/key")
@app.post("/android/api/key")
def key(req: KeyRequest):
    try:
        adbctl.keyevent(req.key)
        return api_ok()
    except Exception as exc:
        return api_error(exc)


@app.get("/api/approvals")
@app.get("/android/api/approvals")
def list_approvals():
    return api_ok({"approvals": approvals.list_approvals()})


@app.post("/api/approvals")
@app.post("/android/api/approvals")
def create_approval(req: ApprovalCreate):
    try:
        item = approvals.create_approval(req.app, req.action, req.message, req.risk)
        return api_ok({"approval": item})
    except Exception as exc:
        return api_error(exc)


@app.get("/api/approvals/{approval_id}")
@app.get("/android/api/approvals/{approval_id}")
def get_approval(approval_id: str):
    item = approvals.get_approval(approval_id)
    if not item:
        raise HTTPException(status_code=404, detail="Approval not found")
    return api_ok({"approval": item})


@app.get("/api/approvals/{approval_id}/screenshot.png")
@app.get("/android/api/approvals/{approval_id}/screenshot.png")
def approval_screenshot(approval_id: str):
    path = approvals.screenshot_path(approval_id)
    if not path.exists() or path.stat().st_size == 0:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/approvals/{approval_id}/approve")
@app.post("/android/api/approvals/{approval_id}/approve")
def approve(approval_id: str):
    item = approvals.update_status(approval_id, "approved")
    if not item:
        raise HTTPException(status_code=404, detail="Approval not found")
    return api_ok({"approval": item})


@app.post("/api/approvals/{approval_id}/deny")
@app.post("/android/api/approvals/{approval_id}/deny")
def deny(approval_id: str):
    item = approvals.update_status(approval_id, "denied")
    if not item:
        raise HTTPException(status_code=404, detail="Approval not found")
    return api_ok({"approval": item})


@app.post("/api/approvals/{approval_id}/edit")
@app.post("/android/api/approvals/{approval_id}/edit")
@app.post("/api/approvals/{approval_id}/take-control")
@app.post("/android/api/approvals/{approval_id}/take-control")
def edit(approval_id: str):
    item = approvals.update_status(approval_id, "editing")
    if not item:
        raise HTTPException(status_code=404, detail="Approval not found")
    return api_ok({"approval": item})


@app.post("/api/approvals/{approval_id}/release-control")
@app.post("/android/api/approvals/{approval_id}/release-control")
def release_control(approval_id: str):
    item = approvals.update_status(approval_id, "pending")
    if not item:
        raise HTTPException(status_code=404, detail="Approval not found")
    return api_ok({"approval": item})
