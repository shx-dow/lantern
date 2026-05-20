"""
TCP file server — listens for incoming connections from other peers
and handles LIST, DOWNLOAD, and UPLOAD commands.

Each client connection is handled in its own thread.  A semaphore limits
the number of concurrent handler threads to MAX_CONNECTIONS to prevent
resource exhaustion from a flood of incoming connections.

Upload flow (with confirmation):
  1. Sender sends:  UPLOAD_REQUEST|<filename>|<filesize>
  2. Server places a UploadRequest object on the pending_uploads queue and
     blocks on request.decision_event (timeout: UPLOAD_REQUEST_TIMEOUT).
  3. The TUI dequeues the request, shows a confirmation modal, then calls
     request.accept() or request.reject().
  4. Server resumes: if accepted it sends OK and receives the file; if
     rejected (or timed out) it sends ERROR and closes the connection.
  Legacy UPLOAD command is kept for CLI-mode compatibility.
"""

import os
import queue
import re
import shutil
import socket
import threading
from dataclasses import dataclass, field

from typing_extensions import Callable

from .config import SEPARATOR, SHARED_DIR, TCP_PORT
from .protocol import recv_file, recv_msg, send_file, send_msg

MAX_CONNECTIONS = 50
UPLOAD_REQUEST_TIMEOUT = 60
MAX_PENDING_UPLOADS = 20


_WINDOWS_RESERVED = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", re.IGNORECASE
)


def _safe_filename(filename: str) -> str:
    """Sanitize an untrusted filename.

    - Strips directory components (prevents path traversal).
    - Removes null bytes.
    - Rejects Windows reserved device names (CON, NUL, COM1 … LPT9).
    - Falls back to "upload" if the result is empty or a bare dot/dotdot.
    """
    name = os.path.basename(filename)
    name = name.replace("\x00", "")
    if name in ("", ".", ".."):
        return "upload"
    if _WINDOWS_RESERVED.match(name):
        return "upload"
    return name


def _is_safe_shared_path(filepath: str) -> bool:
    shared_root = os.path.realpath(SHARED_DIR)
    candidate = os.path.realpath(filepath)
    return os.path.commonpath([shared_root, candidate]) == shared_root


def _has_enough_space(directory: str, required_bytes: int) -> bool:
    try:
        return shutil.disk_usage(directory).free >= required_bytes
    except OSError:
        return False


@dataclass
class UploadRequest:
    """Represents a pending upload awaiting user confirmation."""

    sender_ip: str
    filename: str
    filesize: int
    # Set by accept() / reject() to unblock the server thread
    decision_event: threading.Event = field(default_factory=threading.Event)
    accepted: bool = False
    # Set by the TUI after accepting, to receive progress updates during recv
    progress_callback: Callable[[int, int], None] | None = None
    # Set by the server thread once the transfer finishes (success or failure)
    transfer_done_event: threading.Event = field(default_factory=threading.Event)
    transfer_success: bool = False

    def accept(
        self, progress_callback: Callable[[int, int], None] | None = None
    ) -> None:
        self.progress_callback = progress_callback
        self.accepted = True
        self.decision_event.set()

    def reject(self) -> None:
        self.accepted = False
        self.decision_event.set()


class FileServer:
    """Multithreaded TCP server for file operations."""

    def __init__(self, port: int = TCP_PORT):
        self.port = port
        self._running = False
        self._sock: socket.socket | None = None
        self._semaphore = threading.Semaphore(MAX_CONNECTIONS)
        self.pending_uploads: queue.Queue[UploadRequest] = queue.Queue(
            maxsize=MAX_PENDING_UPLOADS
        )

    def start(self) -> None:
        self._running = True
        thread = threading.Thread(target=self._accept_loop, daemon=True)
        thread.start()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()

    def _accept_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", self.port))
            sock.listen(5)
        except OSError:
            sock.close()
            return
        sock.settimeout(2)
        self._sock = sock

        while self._running:
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            if not self._semaphore.acquire(blocking=False):
                try:
                    conn.close()
                except OSError:
                    pass
                continue

            handler = threading.Thread(
                target=self._handle_client, args=(conn, addr), daemon=True
            )
            handler.start()

        self._sock.close()

    def _handle_client(self, conn: socket.socket, addr: tuple) -> None:
        try:
            command_msg = recv_msg(conn)
            if command_msg is None:
                return

            parts = command_msg.split(SEPARATOR)
            cmd = parts[0].upper()

            if cmd == "LIST":
                self._handle_list(conn)
            elif cmd == "DOWNLOAD" and len(parts) >= 2:
                self._handle_download(conn, parts[1])
            elif cmd == "UPLOAD_REQUEST" and len(parts) >= 3:
                self._handle_upload_request(conn, addr[0], parts[1], parts[2])
            elif cmd == "UPLOAD" and len(parts) >= 3:
                self._handle_upload(conn, parts[1], parts[2])
            else:
                send_msg(conn, f"ERROR{SEPARATOR}Unknown command")
        except Exception:
            try:
                send_msg(conn, f"ERROR{SEPARATOR}Internal server error")
            except Exception:
                pass
        finally:
            conn.close()
            self._semaphore.release()

    def _handle_list(self, conn: socket.socket) -> None:
        os.makedirs(SHARED_DIR, exist_ok=True)

        entries = []
        for name in os.listdir(SHARED_DIR):
            filepath = os.path.join(SHARED_DIR, name)
            if os.path.isfile(filepath):
                size = os.path.getsize(filepath)
                entries.append(f"{name}{SEPARATOR}{size}")

        listing = "\n".join(entries)
        send_msg(conn, f"OK{SEPARATOR}{listing}")

    def _handle_download(self, conn: socket.socket, filename: str) -> None:
        filename = _safe_filename(filename)
        filepath = os.path.join(SHARED_DIR, filename)

        if not os.path.isfile(filepath):
            send_msg(conn, f"ERROR{SEPARATOR}File not found: {filename}")
            return
        if not _is_safe_shared_path(filepath):
            send_msg(conn, f"ERROR{SEPARATOR}Unsafe file path")
            return

        filesize = os.path.getsize(filepath)
        send_msg(conn, f"OK{SEPARATOR}{filesize}")
        send_file(conn, filepath)

    def _handle_upload_request(
        self,
        conn: socket.socket,
        sender_ip: str,
        filename: str,
        filesize_str: str,
    ) -> None:
        filename = _safe_filename(filename)

        try:
            filesize = int(filesize_str)
        except ValueError:
            send_msg(conn, f"ERROR{SEPARATOR}Invalid file size")
            return

        if filesize < 0:
            send_msg(conn, f"ERROR{SEPARATOR}File size must not be negative")
            return

        request = UploadRequest(
            sender_ip=sender_ip,
            filename=filename,
            filesize=filesize,
        )
        try:
            self.pending_uploads.put_nowait(request)
        except queue.Full:
            send_msg(conn, f"ERROR{SEPARATOR}Server is busy, try again later")
            return

        decided = request.decision_event.wait(timeout=UPLOAD_REQUEST_TIMEOUT)

        if not decided or not request.accepted:
            send_msg(conn, f"ERROR{SEPARATOR}Upload declined")
            return

        try:
            os.makedirs(SHARED_DIR, exist_ok=True)
            if not _has_enough_space(SHARED_DIR, filesize):
                send_msg(conn, f"ERROR{SEPARATOR}Not enough free disk space")
                return

            send_msg(conn, "OK")
            filepath = os.path.join(SHARED_DIR, filename)
            if not _is_safe_shared_path(filepath):
                send_msg(conn, f"ERROR{SEPARATOR}Unsafe file path")
                return
            received = recv_file(conn, filepath, filesize, request.progress_callback)

            if received == filesize:
                request.transfer_success = True
                send_msg(conn, f"OK{SEPARATOR}Received {filename} ({filesize} bytes)")
            else:
                send_msg(
                    conn,
                    f"ERROR{SEPARATOR}Incomplete transfer: got {received}/{filesize} bytes",
                )
        finally:
            request.transfer_done_event.set()

    def _handle_upload(
        self, conn: socket.socket, filename: str, filesize_str: str
    ) -> None:
        filename = _safe_filename(filename)
        os.makedirs(SHARED_DIR, exist_ok=True)
        filepath = os.path.join(SHARED_DIR, filename)
        if not _is_safe_shared_path(filepath):
            send_msg(conn, f"ERROR{SEPARATOR}Unsafe file path")
            return

        try:
            filesize = int(filesize_str)
        except ValueError:
            send_msg(conn, f"ERROR{SEPARATOR}Invalid file size")
            return

        if filesize < 0:
            send_msg(conn, f"ERROR{SEPARATOR}File size must not be negative")
            return

        send_msg(conn, "OK")

        received = recv_file(conn, filepath, filesize)

        if received == filesize:
            send_msg(conn, f"OK{SEPARATOR}Received {filename} ({filesize} bytes)")
        else:
            send_msg(
                conn,
                f"ERROR{SEPARATOR}Incomplete transfer: got {received}/{filesize} bytes",
            )
