#!/usr/bin/env python3
"""Smoke test for the AgentPhone WebRTC video endpoint."""
import sys, json, asyncio
from aiortc import RTCPeerConnection, RTCSessionDescription

async def test():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3008/api/webrtc/offer"
    pc = RTCPeerConnection()
    pc.addTransceiver("video", {"direction": "recvonly"})
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}) as resp:
            data = await resp.json()
            if not data.get("ok"):
                sys.exit(1)
    await pc.close()

asyncio.run(test())
