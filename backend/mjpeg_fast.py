"""
Fast MJPEG stream — emulator gRPC RGBA capture → resize → JPEG.
RGBA capture is 32ms vs PNG's 125ms — 4× faster.
Total pipeline: ~50ms = 20fps theoretical.
"""

from __future__ import annotations

import io
import time
from typing import Iterator

import grpc
import numpy as np
from PIL import Image

import emulator_controller_pb2 as ec_pb2
import emulator_controller_pb2_grpc as ec_grpc

_GRPC_CHANNEL: grpc.Channel | None = None
_GRPC_STUB: ec_grpc.EmulatorControllerStub | None = None
_GRPC_OPTS = [("grpc.max_receive_message_length", 50 * 1024 * 1024)]


def _get_stub() -> ec_grpc.EmulatorControllerStub:
    global _GRPC_CHANNEL, _GRPC_STUB
    if _GRPC_STUB is None:
        _GRPC_CHANNEL = grpc.insecure_channel("localhost:8554", options=_GRPC_OPTS)
        _GRPC_STUB = ec_grpc.EmulatorControllerStub(_GRPC_CHANNEL)
    return _GRPC_STUB


def _capture_rgba(target_w: int = 540) -> np.ndarray | None:
    """Capture a single RGBA frame via gRPC, resize, return as numpy RGB array."""
    stub = _get_stub()
    fmt = ec_pb2.ImageFormat(format=ec_pb2.ImageFormat.RGBA8888, width=0, height=0)
    img_msg = stub.getScreenshot(fmt)
    if len(img_msg.image) < 16:
        return None

    # RGBA8888 raw pixels — dimensions may be 0; infer from data size
    data = np.frombuffer(img_msg.image, dtype=np.uint8)
    w = img_msg.width
    h = img_msg.height

    # Infer dimensions from known native resolution if reported as 0
    if w == 0 or h == 0:
        total_pixels = len(data) // 4
        # Native is 1080×2400 = 2,592,000 pixels
        if total_pixels == 1080 * 2400:
            w, h = 1080, 2400
        elif total_pixels == 720 * 1600:
            w, h = 720, 1600
        else:
            # Best guess: assume tall aspect ratio
            h = int((total_pixels * 2400 / 1080) ** 0.5)
            w = total_pixels // h
            if w * h != total_pixels:
                return None

    expected = w * h * 4
    if len(data) < expected:
        return None

    arr = data[:expected].reshape((h, w, 4))
    rgb = arr[:, :, :3]  # strip alpha

    # Resize
    if target_w > 0 and w > target_w:
        ratio = target_w / w
        new_h = int(h * ratio)
        img = Image.fromarray(rgb, "RGB").resize((target_w, new_h), Image.NEAREST)
        return np.array(img)
    return rgb


def fast_jpeg_stream(
    quality: int = 60,
    target_width: int = 540,
    max_fps: int = 20,
) -> Iterator[bytes]:
    """Generate MJPEG frames using emulator gRPC RGBA capture (~32ms)."""
    interval = 1.0 / max_fps
    frame_count = 0
    total_time = 0.0
    t0 = time.monotonic()

    while True:
        t_start = time.monotonic()

        try:
            arr = _capture_rgba(target_w=target_width)
            if arr is None:
                time.sleep(0.05)
                continue

            img = Image.fromarray(arr, "RGB")
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality, optimize=False)
            jpeg = buf.getvalue()

        except Exception:
            time.sleep(0.1)
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
            + jpeg
            + b"\r\n"
        )

        frame_count += 1
        elapsed = time.monotonic() - t_start
        total_time += elapsed

        if frame_count % 30 == 0:
            actual_fps = frame_count / (time.monotonic() - t0)
            avg_ms = (total_time / frame_count) * 1000
            print(f"MJPEG-RGBA: {actual_fps:.0f}fps | avg {avg_ms:.0f}ms | "
                  f"{img.width}x{img.height} | {len(jpeg)//1024}KB")

        remaining = interval - elapsed
        if remaining > 0:
            time.sleep(remaining)