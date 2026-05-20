"""
Protocol helpers for sending/receiving messages and files over TCP sockets.

Message framing uses a 4-byte big-endian length prefix so the receiver
knows exactly how many bytes to read for each message.

    [ 4 bytes: length ][ N bytes: payload ]
"""

import contextlib
import os
import struct
import tempfile
import threading

from typing_extensions import Callable

from .config import BUFFER_SIZE

MAX_MSG_SIZE = 64 * 1024  # 64 KB


def send_msg(sock, text: str) -> None:
    data = text.encode("utf-8")
    length_prefix = struct.pack("!I", len(data))
    sock.sendall(length_prefix + data)


def recv_msg(sock) -> str | None:
    raw_len = _recv_exactly(sock, 4)
    if raw_len is None:
        return None
    msg_len = struct.unpack("!I", raw_len)[0]
    if msg_len > MAX_MSG_SIZE:
        raise ValueError(
            f"Incoming message too large: {msg_len} bytes (max {MAX_MSG_SIZE})"
        )
    raw_data = _recv_exactly(sock, msg_len)
    if raw_data is None:
        return None
    return raw_data.decode("utf-8")

def send_file(sock, filepath: str) -> None:
    if os.path.islink(filepath):
        raise ValueError(f"Refusing to send symlink: {filepath}")

    filesize = os.path.getsize(filepath)
    send_msg(sock, str(filesize))

    with open(filepath, "rb") as f:
        try:
            sock.sendfile(f)
        except AttributeError:
            while True:
                chunk = f.read(BUFFER_SIZE)
                if not chunk:
                    break
                sock.sendall(chunk)


def recv_file(
    sock,
    filepath: str,
    filesize: int,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> int:
    received = 0
    fd = None
    tmp_path = None
    try:
        if os.path.islink(filepath):
            raise ValueError(f"Refusing to write through symlink: {filepath}")

        target_dir = os.path.dirname(filepath) or "."
        fd, tmp_path = tempfile.mkstemp(
            dir=target_dir,
            prefix=f".{os.path.basename(filepath)}.",
            suffix=".part",
        )
        with os.fdopen(fd, "wb") as f:
            fd = None
            while received < filesize:
                if cancel_event and cancel_event.is_set():
                    break
                chunk_size = min(BUFFER_SIZE, filesize - received)
                chunk = _recv_exactly(sock, chunk_size)
                if chunk is None:
                    break
                f.write(chunk)
                received += len(chunk)
                if progress_callback:
                    progress_callback(received, filesize)
        if received == filesize and tmp_path:
            os.replace(tmp_path, filepath)
            tmp_path = None
    except Exception:
        try:
            if tmp_path:
                os.remove(tmp_path)
        except OSError:
            pass
        raise
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)

        if tmp_path:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)

    return received


def _recv_exactly(sock, num_bytes: int) -> bytes | None:
    """Read exactly *num_bytes* from the socket. Returns None on disconnect."""
    data = bytearray()
    while len(data) < num_bytes:
        packet = sock.recv(min(BUFFER_SIZE, num_bytes - len(data)))
        if not packet:
            return None
        data.extend(packet)
    return bytes(data)
