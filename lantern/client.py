"""
TCP client — connects to a remote peer and performs file operations.

Each operation opens a fresh TCP connection, sends a command, processes the
response, and closes the connection.  This keeps the protocol stateless and
simple.

Two API layers:
  - Core functions (fetch_*) return structured data for the TUI.
  - CLI wrappers (list_files, download_file, …) print results for the CLI.
"""

import os
import socket
import threading

from .config import SEPARATOR, BUFFER_SIZE, SHARED_DIR
from .protocol import send_msg, recv_msg, recv_file


def _connect(host: str, port: int, timeout: float = 10) -> socket.socket:
    """Open a TCP connection to a remote peer."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
    except Exception:
        sock.close()
        raise
    return sock


def format_size(size_bytes: int | float) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ======================================================================
# Core API — returns structured data (used by TUI and CLI wrappers)
# ======================================================================


def fetch_file_list(host: str, port: int) -> list[dict]:
    """
    Fetch the file listing from a remote peer.

    Returns a list of dicts: [{"name": str, "size": int}, ...]
    Raises RuntimeError on protocol errors.
    """
    sock = _connect(host, port)
    try:
        send_msg(sock, "LIST")
        response = recv_msg(sock)
        if response is None:
            raise RuntimeError("No response from peer")

        parts = response.split(SEPARATOR, 1)
        if parts[0] != "OK":
            raise RuntimeError(parts[1] if len(parts) > 1 else "Unknown error")

        listing = parts[1] if len(parts) > 1 else ""
        if not listing.strip():
            return []

        files = []
        for line in listing.split("\n"):
            if SEPARATOR in line:
                name, size_str = line.split(SEPARATOR, 1)
                files.append({"name": name, "size": int(size_str)})
        return files
    finally:
        sock.close()


def do_download(
    host: str,
    port: int,
    filename: str,
    progress_callback: callable = None,
    cancel_event: threading.Event = None,
) -> tuple[str, int]:
    """
    Download a file from a remote peer.

    Returns (destination_path, bytes_received).
    Raises RuntimeError on failure.
    progress_callback: optional callable(current_bytes, total_bytes) for UI updates
    cancel_event: optional threading.Event to cancel the transfer
    """
    sock = _connect(host, port, timeout=30)
    try:
        send_msg(sock, f"DOWNLOAD{SEPARATOR}{filename}")
        response = recv_msg(sock)
        if response is None:
            raise RuntimeError("No response from peer")

        if response.startswith("ERROR"):
            parts = response.split(SEPARATOR, 1)
            raise RuntimeError(parts[1] if len(parts) > 1 else "Unknown error")

        parts = response.split(SEPARATOR, 1)
        if parts[0] != "OK" or len(parts) < 2:
            raise RuntimeError("Invalid response from peer")

        try:
            filesize = int(parts[1])
        except ValueError:
            raise RuntimeError(f"Invalid file size in response: {parts[1]}")

        os.makedirs(SHARED_DIR, exist_ok=True)
        # Sanitize the filename to prevent path traversal: a malicious server
        # could return a filename like "../../.bashrc" in its file listing.
        safe_name = os.path.basename(filename)
        if not safe_name:
            raise RuntimeError(
                f"Filename is invalid or empty after sanitization: {filename!r}"
            )
        dest = os.path.join(SHARED_DIR, safe_name)
        received = recv_file(sock, dest, filesize, progress_callback, cancel_event)

        if cancel_event and cancel_event.is_set():
            raise RuntimeError("Transfer cancelled")

        return dest, received
    finally:
        sock.close()


def do_upload(host: str, port: int, filepath: str) -> str:
    """
    Upload a local file to a remote peer.

    Returns a success message string.
    Raises RuntimeError on failure.
    """
    if not os.path.isfile(filepath):
        raise RuntimeError(f"Local file not found: {filepath}")

    filename = os.path.basename(filepath)
    filesize = os.path.getsize(filepath)

    sock = _connect(host, port)
    try:
        send_msg(sock, f"UPLOAD{SEPARATOR}{filename}{SEPARATOR}{filesize}")

        response = recv_msg(sock)
        if response is None or not response.startswith("OK"):
            parts = (response or "").split(SEPARATOR, 1)
            raise RuntimeError(
                f"Peer rejected upload: {parts[1] if len(parts) > 1 else 'unknown'}"
            )

        sent = 0
        with open(filepath, "rb") as f:
            while sent < filesize:
                chunk = f.read(BUFFER_SIZE)
                if not chunk:
                    break
                sock.sendall(chunk)
                sent += len(chunk)

        confirm = recv_msg(sock)
        if confirm and confirm.startswith("OK"):
            parts = confirm.split(SEPARATOR, 1)
            return parts[1] if len(parts) > 1 else "Upload complete"
        else:
            parts = (confirm or "").split(SEPARATOR, 1)
            raise RuntimeError(
                f"Upload issue: {parts[1] if len(parts) > 1 else 'unknown'}"
            )
    finally:
        sock.close()


# ======================================================================
# CLI wrappers — print results (used by peer.py CLI mode)
# ======================================================================


def list_files(host: str, port: int) -> None:
    """Print the file listing from a remote peer."""
    try:
        files = fetch_file_list(host, port)
    except RuntimeError as e:
        print(f"  [!] {e}")
        return

    if not files:
        print("  (no files)")
        return

    print(f"  {'Filename':<40} {'Size':>12}")
    print(f"  {'-' * 40} {'-' * 12}")
    for f in files:
        print(f"  {f['name']:<40} {format_size(f['size']):>12}")


def download_file(host: str, port: int, filename: str) -> None:
    """Download a file and print the result."""
    try:
        dest, received = do_download(host, port, filename)
        print(f"  Downloaded {filename} ({format_size(received)}) -> {dest}")
    except RuntimeError as e:
        print(f"  [!] {e}")


def upload_file(host: str, port: int, filepath: str) -> None:
    """Upload a file and print the result."""
    try:
        msg = do_upload(host, port, filepath)
        print(f"  {msg}")
    except RuntimeError as e:
        print(f"  [!] {e}")
