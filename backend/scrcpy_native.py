from __future__ import annotations

import os
import queue
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import av
from av.codec import CodecContext

import adbctl

AGENTPHONE_HOME = Path(os.environ.get("AGENTPHONE_HOME", Path.home() / "agentphone"))
SCRCPY_SERVER = Path(os.environ.get("AGENTPHONE_SCRCPY_SERVER", "/usr/share/scrcpy/scrcpy-server"))
REMOTE_SERVER = "/data/local/tmp/scrcpy-server-agentphone"
SCRCPY_PORT = int(os.environ.get("AGENTPHONE_SCRCPY_PORT", "27183"))
SCRCPY_VERSION = os.environ.get("AGENTPHONE_SCRCPY_VERSION", "1.25")
SCRCPY_BITRATE = int(os.environ.get("AGENTPHONE_SCRCPY_BITRATE", "16000000"))
SCRCPY_MAX_FPS = int(os.environ.get("AGENTPHONE_SCRCPY_MAX_FPS", "15"))
SCRCPY_MAX_SIZE = int(os.environ.get("AGENTPHONE_SCRCPY_MAX_SIZE", "0"))


def _adb_cmd(*args: str) -> list[str]:
    return [str(adbctl.ADB), *args]


def _run_adb(*args: str, check: bool = True, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(_adb_cmd(*args), capture_output=True, text=True, check=check, timeout=timeout)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise EOFError(f"scrcpy stream ended during handshake ({len(data)}/{size})")
        data += chunk
    return data


class ScrcpyNativeStream:
    """Low-latency Android video using scrcpy-server's native H.264 capture path.

    The stream is decoded into VideoFrame objects because aiortc's public
    VideoStreamTrack API accepts frames, not pre-encoded H.264 packets. This
    still avoids the slow ADB screencap PNG/RGBA path and keeps only the newest
    frame to prevent multi-second queueing.
    """

    def __init__(self) -> None:
        self.frame_queue: queue.Queue[av.VideoFrame] = queue.Queue(maxsize=1)
        self.proc: Optional[subprocess.Popen] = None
        self.sock: Optional[socket.socket] = None
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.error: Optional[str] = None
        self.device_name = ""
        self.width = 0
        self.height = 0
        self.started_at = time.time()
        self._start()

    def _start(self) -> None:
        if not SCRCPY_SERVER.exists():
            raise FileNotFoundError(f"scrcpy-server not found at {SCRCPY_SERVER}")
        # Clean up any previous AgentPhone native stream. This only targets the
        # scrcpy server process and the registered local ADB-forward port.
        subprocess.run(_adb_cmd("forward", "--remove", f"tcp:{SCRCPY_PORT}"), capture_output=True)
        subprocess.run(_adb_cmd("shell", "pkill", "-f", "com.genymobile.scrcpy.Server"), capture_output=True)
        _run_adb("push", str(SCRCPY_SERVER), REMOTE_SERVER, timeout=20)
        _run_adb("forward", f"tcp:{SCRCPY_PORT}", "localabstract:scrcpy", timeout=10)

        args = [
            f"CLASSPATH={REMOTE_SERVER}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            SCRCPY_VERSION,
            "log_level=info",
            f"bit_rate={SCRCPY_BITRATE}",
            f"max_fps={SCRCPY_MAX_FPS}",
            "tunnel_forward=true",
            "control=false",
            "send_frame_meta=false",
            "clipboard_autosync=false",
            "power_off_on_close=false",
            "cleanup=false",
        ]
        if SCRCPY_MAX_SIZE > 0:
            args.insert(6, f"max_size={SCRCPY_MAX_SIZE}")

        self.proc = subprocess.Popen(
            _adb_cmd("shell", *args),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=False,
        )

        last_error: Optional[BaseException] = None
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"scrcpy server exited early with code {self.proc.returncode}")
            try:
                sock = socket.create_connection(("127.0.0.1", SCRCPY_PORT), timeout=1)
                sock.settimeout(2)
                dummy = _recv_exact(sock, 1)
                if dummy != b"\x00":
                    raise RuntimeError(f"bad scrcpy dummy byte: {dummy!r}")
                name = _recv_exact(sock, 64).decode("utf-8", errors="replace").rstrip("\x00")
                self.width, self.height = struct.unpack(">HH", _recv_exact(sock, 4))
                self.device_name = name
                self.sock = sock
                break
            except BaseException as exc:  # retry while Android server opens local socket
                last_error = exc
                try:
                    sock.close()  # type: ignore[name-defined]
                except Exception:
                    pass
                time.sleep(0.1)
        else:
            self.stop()
            raise RuntimeError(f"scrcpy handshake failed: {last_error!r}")

        self.thread = threading.Thread(target=self._decode_loop, name="agentphone-scrcpy-decode", daemon=True)
        self.thread.start()

    def _decode_loop(self) -> None:
        assert self.sock is not None
        codec = CodecContext.create("h264", "r")
        self.sock.settimeout(1)
        try:
            while not self.stop_event.is_set():
                try:
                    chunk = self.sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    raise EOFError("scrcpy H.264 stream ended")
                for packet in codec.parse(chunk):
                    for frame in codec.decode(packet):
                        # Keep only the newest frame so a slow browser never
                        # builds up seconds of stale queued video.
                        try:
                            while True:
                                self.frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            self.frame_queue.put_nowait(frame)
                        except queue.Full:
                            pass
        except BaseException as exc:
            self.error = str(exc)
        finally:
            self.stop_event.set()
            if self.sock is not None:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
            if self.proc is not None and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                    self.proc.wait(timeout=1.5)
                except Exception:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass
            subprocess.run(_adb_cmd("forward", "--remove", f"tcp:{SCRCPY_PORT}"), capture_output=True)

    def latest_frame(self, timeout: float = 0.35) -> Optional[av.VideoFrame]:
        if self.stop_event.is_set() and self.frame_queue.empty():
            return None
        try:
            return self.frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        self.stop_event.set()
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=1.5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        subprocess.run(_adb_cmd("forward", "--remove", f"tcp:{SCRCPY_PORT}"), capture_output=True)
