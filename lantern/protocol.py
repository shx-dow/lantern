"""
Protocol helpers for sending/receiving messages and files over TCP sockets.

Message framing uses a 4-byte big-endian length prefix so the receiver
knows exactly how many bytes to read for each message.

    [ 4 bytes: length ][ N bytes: payload ]
"""

import os
import struct
import threading

from typing_extensions import Callable

from .config import BUFFER_SIZE

# Maximum size of a single control message (commands, responses, listings).
# A 64 KB cap prevents a malicious peer from causing memory exhaustion by
# sending a fabricated 4-byte length prefix claiming a huge payload.
MAX_MSG_SIZE = 64 * 1024  # 64 KB


# ---------------------------------------------------------------------------
# Message framing (for control messages: commands, responses, file listings)
# ---------------------------------------------------------------------------


def send_msg(sock, text: str) -> None:
    """Send a UTF-8 string with a 4-byte length prefix."""
    data = text.encode("utf-8")
    length_prefix = struct.pack("!I", len(data))
    sock.sendall(length_prefix + data)


def recv_msg(sock) -> str | None:
    """Receive a length-prefixed UTF-8 string. Returns None on disconnect.

    Raises ValueError if the declared message length exceeds MAX_MSG_SIZE,
    preventing memory exhaustion from a malicious peer.
    """
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


# ---------------------------------------------------------------------------
# File transfer
# ---------------------------------------------------------------------------


def send_file(sock, filepath: str) -> None:
    """Send a file: first a message with the file size, then raw bytes.

    Uses socket.sendfile() for zero-copy OS-level transfer when available,
    falling back to a manual chunk loop otherwise.
    """
    filesize = os.path.getsize(filepath)
    send_msg(sock, str(filesize))

    with open(filepath, "rb") as f:
        try:
            sock.sendfile(f)
        except AttributeError:
            # Fallback for platforms where sendfile is unavailable
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
    """
    Receive a file: read filesize raw bytes and write them to *filepath*.

    Returns the number of bytes received.  If the transfer is cancelled or
    the connection drops before completion, the partial file is deleted so
    the shared directory is never left with corrupt data.

    progress_callback: optional callable(current_bytes, total_bytes)
    cancel_event: optional threading.Event to cancel the transfer
    """
    received = 0
    try:
        with open(filepath, "wb") as f:
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
    except Exception:
        # Remove the partial file before re-raising
        try:
            os.remove(filepath)
        except OSError:
            pass
        raise

    if received < filesize:
        # Incomplete transfer (cancelled or disconnected) — clean up
        try:
            os.remove(filepath)
        except OSError:
            pass

    return received


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _recv_exactly(sock, num_bytes: int) -> bytes | None:
    """Read exactly *num_bytes* from the socket. Returns None on disconnect."""
    data = bytearray()
    while len(data) < num_bytes:
        packet = sock.recv(min(BUFFER_SIZE, num_bytes - len(data)))
        if not packet:
            return None
        data.extend(packet)
    return bytes(data)
