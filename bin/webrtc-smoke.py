#!/home/ryancalpin/agentphone/backend/.venv/bin/python
from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.request

from aiortc import RTCPeerConnection, RTCSessionDescription

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3008/api/webrtc/offer"


async def wait_ice(pc: RTCPeerConnection, timeout: float = 3.0) -> None:
    start = time.time()
    while pc.iceGatheringState != "complete" and time.time() - start < timeout:
        await asyncio.sleep(0.05)


async def main() -> int:
    pc = RTCPeerConnection()
    got_track = asyncio.Event()
    frame_result: dict[str, object] = {}

    @pc.on("track")
    def on_track(track):
        if track.kind != "video":
            return
        got_track.set()

        async def reader() -> None:
            try:
                frame = await asyncio.wait_for(track.recv(), timeout=12)
                frame_result["width"] = frame.width
                frame_result["height"] = frame.height
            except Exception as exc:  # pragma: no cover - smoke script output
                frame_result["error"] = repr(exc)

        asyncio.create_task(reader())

    try:
        pc.addTransceiver("video", direction="recvonly")
        await pc.setLocalDescription(await pc.createOffer())
        await wait_ice(pc)
        payload = json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}).encode()
        req = urllib.request.Request(URL, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as response:
            answer = json.loads(response.read().decode())
        if not answer.get("ok"):
            print(f"offer failed: {answer}", file=sys.stderr)
            return 1
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
        await asyncio.wait_for(got_track.wait(), timeout=6)
        start = time.time()
        while not frame_result and time.time() - start < 15:
            await asyncio.sleep(0.1)
        if not frame_result or "error" in frame_result:
            print(f"no frame: {frame_result}", file=sys.stderr)
            return 1
        print(f"WebRTC frame {frame_result['width']}x{frame_result['height']}")
        return 0
    finally:
        await pc.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
