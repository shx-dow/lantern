"""
Lantern — P2P File Sharing System

Main entry point.  Starts the discovery beacon, TCP file server, and
either a CLI loop or a full TUI dashboard.

Usage:
    python peer.py              # start TUI mode (default)
    python peer.py --cli        # start CLI mode
    python peer.py --port 6000  # use a custom TCP port
"""

import argparse
import os
import sys

from .config import TCP_PORT, SHARED_DIR, PEER_ID
from .discovery import PeerDiscovery
from .server import FileServer
from .client import list_files, download_file, upload_file


def _format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _parse_target(target: str, default_port: int) -> tuple[str, int]:
    """
    Parse a 'host:port' string.  If port is omitted, *default_port* is used.
    """
    if ":" in target:
        host, port_str = target.rsplit(":", 1)
        return host, int(port_str)
    return target, default_port


def _print_help() -> None:
    print("""
  Lantern — P2P File Sharing Commands
  ────────────────────────────────────────────────────
  peers                            Show discovered peers on the LAN
  list <host[:port]>               List files on a remote peer
  download <host[:port]> <file>    Download a file from a peer
  upload <host[:port]> <file>      Upload a local file to a peer
  myfiles                          List your own shared files
  help                             Show this help message
  quit / exit                      Shut down this peer
  ────────────────────────────────────────────────────
""")


def _list_local_files() -> None:
    """Print files in the local shared directory."""
    os.makedirs(SHARED_DIR, exist_ok=True)
    files = [
        f for f in os.listdir(SHARED_DIR) if os.path.isfile(os.path.join(SHARED_DIR, f))
    ]

    if not files:
        print("  (no files in shared_files/)")
        return

    print(f"  {'Filename':<40} {'Size':>12}")
    print(f"  {'-' * 40} {'-' * 12}")
    for name in sorted(files):
        size = os.path.getsize(os.path.join(SHARED_DIR, name))
        print(f"  {name:<40} {_format_size(size):>12}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Lantern P2P File Sharing")
    parser.add_argument(
        "--port", type=int, default=TCP_PORT, help="TCP port to listen on"
    )
    parser.add_argument(
        "--cli", action="store_true", help="Launch CLI mode instead of TUI dashboard"
    )
    args = parser.parse_args()

    tcp_port = args.port

    # Ensure shared directory exists
    os.makedirs(SHARED_DIR, exist_ok=True)

    # Start discovery
    discovery = PeerDiscovery(tcp_port=tcp_port)
    discovery.start()

    # Start file server
    server = FileServer(port=tcp_port)
    server.start()

    # ── CLI mode ──
    if args.cli:
        print(f"  Lantern started  [peer_id={PEER_ID}  tcp_port={tcp_port}]")
        print(f"  Shared directory: {SHARED_DIR}")
        print("  Type 'help' for available commands.\n")
    else:
        # ── TUI mode (default) ──
        from .tui import run_tui

        try:
            run_tui(discovery, server, tcp_port)
        finally:
            discovery.stop()
            server.stop()
        return

    # CLI loop
    try:
        while True:
            try:
                raw = input("lantern> ").strip()
            except EOFError:
                break

            if not raw:
                continue

            tokens = raw.split()
            cmd = tokens[0].lower()

            # ----------------------------------------------------------
            if cmd in ("quit", "exit"):
                print("  Shutting down...")
                break

            # ----------------------------------------------------------
            elif cmd == "help":
                _print_help()

            # ----------------------------------------------------------
            elif cmd == "peers":
                peers = discovery.get_peers()
                if not peers:
                    print("  No peers discovered yet (waiting for beacons...).")
                else:
                    print(f"  {'Peer ID':<12} {'Hostname':<20} {'Address':>22}")
                    print(f"  {'-' * 12} {'-' * 20} {'-' * 22}")
                    for p in peers:
                        addr = f"{p['ip']}:{p['tcp_port']}"
                        print(f"  {p['peer_id']:<12} {p['hostname']:<20} {addr:>22}")

            # ----------------------------------------------------------
            elif cmd == "myfiles":
                _list_local_files()

            # ----------------------------------------------------------
            elif cmd == "list":
                if len(tokens) < 2:
                    print("  Usage: list <host[:port]>")
                    continue
                host, port = _parse_target(tokens[1], tcp_port)
                try:
                    list_files(host, port)
                except Exception as e:
                    print(f"  [!] Connection failed: {e}")

            # ----------------------------------------------------------
            elif cmd == "download":
                if len(tokens) < 3:
                    print("  Usage: download <host[:port]> <filename>")
                    continue
                host, port = _parse_target(tokens[1], tcp_port)
                filename = tokens[2]
                try:
                    download_file(host, port, filename)
                except Exception as e:
                    print(f"  [!] Download failed: {e}")

            # ----------------------------------------------------------
            elif cmd == "upload":
                if len(tokens) < 3:
                    print("  Usage: upload <host[:port]> <filepath>")
                    continue
                host, port = _parse_target(tokens[1], tcp_port)
                filepath = tokens[2]
                try:
                    upload_file(host, port, filepath)
                except Exception as e:
                    print(f"  [!] Upload failed: {e}")

            # ----------------------------------------------------------
            else:
                print(f"  Unknown command: {cmd}  (type 'help' for commands)")

    except KeyboardInterrupt:
        print("\n  Interrupted. Shutting down...")

    discovery.stop()
    server.stop()
    print("  Goodbye.")


if __name__ == "__main__":
    main()
