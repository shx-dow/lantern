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
import socket
import threading
from dataclasses import dataclass, field

from .config import TCP_PORT, SHARED_DIR, SEPARATOR
from .protocol import send_msg, recv_msg, send_file, recv_file

# Maximum number of simultaneous client connections handled at once.
MAX_CONNECTIONS = 50

# Seconds the server will wait for the user to accept/reject an upload request.
UPLOAD_REQUEST_TIMEOUT = 60


# Windows reserved device names that must never be used as filenames.
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
    # Strip directory components
    name = os.path.basename(filename)
    # Remove null bytes
    name = name.replace("\x00", "")
    # Reject empty, ".", ".."
    if name in ("", ".", ".."):
        return "upload"
    # Reject Windows reserved names
    if _WINDOWS_RESERVED.match(name):
        return "upload"
    return name


@dataclass
class UploadRequest:
    """Represents a pending upload awaiting user confirmation."""

    sender_ip: str
    filename: str
    filesize: int
    # Set by accept() / reject() to unblock the server thread
    decision_event: threading.Event = field(default_factory=threading.Event)
    accepted: bool = False

    def accept(self) -> None:
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
        # Queue of UploadRequest objects waiting for TUI confirmation.
        self.pending_uploads: queue.Queue[UploadRequest] = queue.Queue()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the server in a daemon thread."""
        self._running = True
        thread = threading.Thread(target=self._accept_loop, daemon=True)
        thread.start()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()

    # ------------------------------------------------------------------
    # Accept loop
    # ------------------------------------------------------------------

    def _accept_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", self.port))
            sock.listen(5)
        except OSError:
            sock.close()
            return
        sock.settimeout(2)  # so we can check self._running periodically
        self._sock = sock

        while self._running:
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            if not self._semaphore.acquire(blocking=False):
                # Too many concurrent connections — reject gracefully.
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

    # ------------------------------------------------------------------
    # Client handler — dispatches commands
    # ------------------------------------------------------------------

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
                # Legacy: used by CLI mode (no confirmation)
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

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _handle_list(self, conn: socket.socket) -> None:
        """Send back a listing of files in the shared directory."""
        os.makedirs(SHARED_DIR, exist_ok=True)

        entries = []
        for name in os.listdir(SHARED_DIR):
            filepath = os.path.join(SHARED_DIR, name)
            if os.path.isfile(filepath):
                size = os.path.getsize(filepath)
                entries.append(f"{name}{SEPARATOR}{size}")

        # Join all entries with a newline; empty string means no files
        listing = "\n".join(entries)
        send_msg(conn, f"OK{SEPARATOR}{listing}")

    def _handle_download(self, conn: socket.socket, filename: str) -> None:
        """Send the requested file to the peer."""
        filename = _safe_filename(filename)
        filepath = os.path.join(SHARED_DIR, filename)

        if not os.path.isfile(filepath):
            send_msg(conn, f"ERROR{SEPARATOR}File not found: {filename}")
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
        """Handle a TUI upload: pause and wait for user confirmation."""
        filename = _safe_filename(filename)

        try:
            filesize = int(filesize_str)
        except ValueError:
            send_msg(conn, f"ERROR{SEPARATOR}Invalid file size")
            return

        if filesize < 0:
            send_msg(conn, f"ERROR{SEPARATOR}File size must not be negative")
            return

        # Build the request and enqueue it for the TUI to handle.
        request = UploadRequest(
            sender_ip=sender_ip,
            filename=filename,
            filesize=filesize,
        )
        self.pending_uploads.put(request)

        # Block this thread until the user decides (or timeout).
        decided = request.decision_event.wait(timeout=UPLOAD_REQUEST_TIMEOUT)

        if not decided or not request.accepted:
            send_msg(conn, f"ERROR{SEPARATOR}Upload declined")
            return

        # User accepted — proceed exactly like a normal upload.
        send_msg(conn, "OK")
        os.makedirs(SHARED_DIR, exist_ok=True)
        filepath = os.path.join(SHARED_DIR, filename)
        received = recv_file(conn, filepath, filesize)

        if received == filesize:
            send_msg(conn, f"OK{SEPARATOR}Received {filename} ({filesize} bytes)")
        else:
            send_msg(
                conn,
                f"ERROR{SEPARATOR}Incomplete transfer: got {received}/{filesize} bytes",
            )

    def _handle_upload(
        self, conn: socket.socket, filename: str, filesize_str: str
    ) -> None:
        """Receive a file from the peer and save it (legacy CLI, no confirmation)."""
        filename = _safe_filename(filename)
        os.makedirs(SHARED_DIR, exist_ok=True)
        filepath = os.path.join(SHARED_DIR, filename)

        try:
            filesize = int(filesize_str)
        except ValueError:
            send_msg(conn, f"ERROR{SEPARATOR}Invalid file size")
            return

        if filesize < 0:
            send_msg(conn, f"ERROR{SEPARATOR}File size must not be negative")
            return

        # Tell the sender we're ready
        send_msg(conn, "OK")

        # Receive the file using the shared protocol helper
        received = recv_file(conn, filepath, filesize)

        if received == filesize:
            send_msg(conn, f"OK{SEPARATOR}Received {filename} ({filesize} bytes)")
        else:
            send_msg(
                conn,
                f"ERROR{SEPARATOR}Incomplete transfer: got {received}/{filesize} bytes",
            )
