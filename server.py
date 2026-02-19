"""
TCP file server — listens for incoming connections from other peers
and handles LIST, DOWNLOAD, UPLOAD, and DELETE commands.

Each client connection is handled in its own thread.
"""

import os
import socket
import threading

from config import TCP_PORT, SHARED_DIR, SEPARATOR, BUFFER_SIZE
from protocol import send_msg, recv_msg, send_file, recv_file


def _safe_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal attacks."""
    return os.path.basename(filename)


class FileServer:
    """Multithreaded TCP server for file operations."""

    def __init__(self, port: int = TCP_PORT):
        self.port = port
        self._running = False
        self._sock: socket.socket | None = None

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
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self.port))
        self._sock.listen(5)
        self._sock.settimeout(2)  # so we can check self._running periodically

        while self._running:
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

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
            elif cmd == "UPLOAD" and len(parts) >= 3:
                self._handle_upload(conn, parts[1], parts[2])
            elif cmd == "DELETE" and len(parts) >= 2:
                self._handle_delete(conn, parts[1])
            else:
                send_msg(conn, f"ERROR{SEPARATOR}Unknown command: {command_msg}")
        except Exception as e:
            try:
                send_msg(conn, f"ERROR{SEPARATOR}{e}")
            except Exception:
                pass
        finally:
            conn.close()

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

        send_msg(conn, "OK")
        send_file(conn, filepath)

    def _handle_upload(self, conn: socket.socket, filename: str, filesize_str: str) -> None:
        """Receive a file from the peer and save it."""
        filename = _safe_filename(filename)
        os.makedirs(SHARED_DIR, exist_ok=True)
        filepath = os.path.join(SHARED_DIR, filename)

        try:
            filesize = int(filesize_str)
        except ValueError:
            send_msg(conn, f"ERROR{SEPARATOR}Invalid file size: {filesize_str}")
            return

        # Tell the sender we're ready
        send_msg(conn, "OK")

        # Receive the raw file bytes (no length-prefix; we already know the size)
        received = 0
        with open(filepath, "wb") as f:
            while received < filesize:
                chunk_size = min(BUFFER_SIZE, filesize - received)
                chunk = conn.recv(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                received += len(chunk)

        if received == filesize:
            send_msg(conn, f"OK{SEPARATOR}Received {filename} ({filesize} bytes)")
        else:
            send_msg(conn, f"ERROR{SEPARATOR}Incomplete transfer: got {received}/{filesize} bytes")

    def _handle_delete(self, conn: socket.socket, filename: str) -> None:
        """Delete a file from the shared directory."""
        filename = _safe_filename(filename)
        filepath = os.path.join(SHARED_DIR, filename)

        if not os.path.isfile(filepath):
            send_msg(conn, f"ERROR{SEPARATOR}File not found: {filename}")
            return

        try:
            os.remove(filepath)
            send_msg(conn, f"OK{SEPARATOR}Deleted {filename}")
        except OSError as e:
            send_msg(conn, f"ERROR{SEPARATOR}Could not delete {filename}: {e}")
