"""
Protocol helpers for sending/receiving messages and files over TCP sockets.

Message framing uses a 4-byte big-endian length prefix so the receiver
knows exactly how many bytes to read for each message.

    [ 4 bytes: length ][ N bytes: payload ]
"""

import struct
import os

from .config import BUFFER_SIZE


# ---------------------------------------------------------------------------
# Message framing (for control messages: commands, responses, file listings)
# ---------------------------------------------------------------------------

def send_msg(sock, text: str) -> None:
    """Send a UTF-8 string with a 4-byte length prefix."""
    data = text.encode("utf-8")
    length_prefix = struct.pack("!I", len(data))
    sock.sendall(length_prefix + data)


def recv_msg(sock) -> str | None:
    """Receive a length-prefixed UTF-8 string. Returns None on disconnect."""
    raw_len = _recv_exactly(sock, 4)
    if raw_len is None:
        return None
    msg_len = struct.unpack("!I", raw_len)[0]
    raw_data = _recv_exactly(sock, msg_len)
    if raw_data is None:
        return None
    return raw_data.decode("utf-8")


# ---------------------------------------------------------------------------
# File transfer
# ---------------------------------------------------------------------------

def send_file(sock, filepath: str) -> None:
    """Send a file: first a message with the file size, then raw bytes."""
    filesize = os.path.getsize(filepath)
    send_msg(sock, str(filesize))

    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(BUFFER_SIZE)
            if not chunk:
                break
            sock.sendall(chunk)


def recv_file(sock, filepath: str) -> int:
    """
    Receive a file: read the size message first, then read that many raw bytes
    and write them to *filepath*.

    Returns the number of bytes received.
    """
    size_msg = recv_msg(sock)
    if size_msg is None:
        return 0
    filesize = int(size_msg)

    received = 0
    with open(filepath, "wb") as f:
        while received < filesize:
            chunk_size = min(BUFFER_SIZE, filesize - received)
            chunk = _recv_exactly(sock, chunk_size)
            if chunk is None:
                break
            f.write(chunk)
            received += len(chunk)

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
