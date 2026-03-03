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

from .client import download_file, list_files, upload_file
from .config import PEER_ID, SHARED_DIR, TCP_PORT
from .discovery import PeerDiscovery
from .server import FileServer
from .updater import check_for_updates


def main() -> None:
    parser = argparse.ArgumentParser(description="Lantern P2P File Sharing")
    parser.add_argument(
        "--port", type=int, default=TCP_PORT, help="TCP port to listen on (1-65535)"
    )
    parser.add_argument(
        "--cli", action="store_true", help="Launch CLI mode instead of TUI dashboard"
    )
    args = parser.parse_args()

    check_for_updates()

    tcp_port = args.port
    if not (1 <= tcp_port <= 65535):
        parser.error(f"--port must be between 1 and 65535 (got {tcp_port})")

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
                print("  Available commands:")
                print("    help                       Show this help message")
                print("    peers                      List discovered peers")
                print("    myfiles                    List files in shared directory")
                print("    list <host[:port]>         List files on a peer")
                print("    download <host[:port]> <filename>  Download a file")
                print("    upload <host[:port]> <filepath>    Upload a file")
                print("    quit, exit                 Exit Lantern")

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
                try:
                    files = os.listdir(SHARED_DIR)
                    if not files:
                        print("  No files in shared directory.")
                    else:
                        print("  Shared files:")
                        for f in sorted(files):
                            fpath = os.path.join(SHARED_DIR, f)
                            if os.path.isfile(fpath):
                                size = os.path.getsize(fpath)
                                print(f"    {f} ({size} bytes)")
                except Exception as e:
                    print(f"  [!] Error listing files: {e}")

            # ----------------------------------------------------------
            elif cmd == "list":
                if len(tokens) < 2:
                    print("  Usage: list <host[:port]>")
                    continue
                target_str = tokens[1]
                if ":" in target_str:
                    try:
                        host, port_str = target_str.rsplit(":", 1)
                        port = int(port_str)
                    except ValueError:
                        print(f"  [!] Invalid host:port format: {target_str}")
                        continue
                else:
                    host = target_str
                    port = tcp_port
                try:
                    list_files(host, port)
                except Exception as e:
                    print(f"  [!] Connection failed: {e}")

            # ----------------------------------------------------------
            elif cmd == "download":
                if len(tokens) < 3:
                    print("  Usage: download <host[:port]> <filename>")
                    continue
                target_str = tokens[1]
                if ":" in target_str:
                    try:
                        host, port_str = target_str.rsplit(":", 1)
                        port = int(port_str)
                    except ValueError:
                        print(f"  [!] Invalid host:port format: {target_str}")
                        continue
                else:
                    host = target_str
                    port = tcp_port
                filename = os.path.basename(tokens[2])
                if not filename:
                    print("  [!] Invalid filename.")
                    continue
                try:
                    download_file(host, port, filename)
                except Exception as e:
                    print(f"  [!] Download failed: {e}")

            # ----------------------------------------------------------
            elif cmd == "upload":
                if len(tokens) < 3:
                    print("  Usage: upload <host[:port]> <filepath>")
                    continue
                target_str = tokens[1]
                if ":" in target_str:
                    try:
                        host, port_str = target_str.rsplit(":", 1)
                        port = int(port_str)
                    except ValueError:
                        print(f"  [!] Invalid host:port format: {target_str}")
                        continue
                else:
                    host = target_str
                    port = tcp_port
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
