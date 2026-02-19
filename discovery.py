"""
Peer discovery via UDP broadcast.

Each peer periodically broadcasts a beacon packet on the LAN.  All peers
listen on the same UDP port and maintain a dict of known peers, expiring
entries that haven't been seen recently.

Beacon payload format (UTF-8 string):
    LANTERN_DISCOVER:<peer_id>:<hostname>:<tcp_port>
"""

import socket
import threading
import time
import platform

from config import UDP_PORT, TCP_PORT, BROADCAST_INTERVAL, PEER_TIMEOUT, PEER_ID

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


def get_broadcast_addresses():
    """Get all broadcast addresses for local interfaces."""
    if not PSUTIL_AVAILABLE:
        return ["<broadcast>", "255.255.255.255"]
    
    broadcasts = []
    
    for iface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET:
                if addr.address.startswith("127."):
                    continue
                ip_parts = addr.address.split('.')
                mask_parts = addr.netmask.split('.')
                broadcast = '.'.join(
                    str(int(ip_parts[i]) | (255 - int(mask_parts[i])))
                    for i in range(4)
                )
                broadcasts.append(broadcast)
    
    return broadcasts if broadcasts else ["255.255.255.255"]


class PeerDiscovery:
    """Manages LAN peer discovery using UDP broadcast."""

    def __init__(self, tcp_port: int = TCP_PORT):
        self.tcp_port = tcp_port
        self.peer_id = PEER_ID
        self.hostname = platform.node() or "unknown"

        self._peers: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._running = False

    def start(self) -> None:
        """Start the beacon and listener threads (daemon threads)."""
        self._running = True

        beacon_thread = threading.Thread(target=self._beacon_loop, daemon=True)
        listener_thread = threading.Thread(target=self._listener_loop, daemon=True)

        beacon_thread.start()
        listener_thread.start()

    def stop(self) -> None:
        self._running = False

    def get_peers(self) -> list[dict]:
        """Return a list of currently active peers (excluding self)."""
        now = time.time()
        active = []
        with self._lock:
            expired = []
            for pid, info in self._peers.items():
                if now - info["last_seen"] > PEER_TIMEOUT:
                    expired.append(pid)
                else:
                    active.append({
                        "peer_id": pid,
                        "ip": info["ip"],
                        "hostname": info["hostname"],
                        "tcp_port": info["tcp_port"],
                    })
            for pid in expired:
                del self._peers[pid]
        return active

    def _beacon_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(1)

        payload = f"LANTERN_DISCOVER:{self.peer_id}:{self.hostname}:{self.tcp_port}"
        data = payload.encode("utf-8")

        try:
            broadcasts = get_broadcast_addresses()
        except Exception:
            broadcasts = ["<broadcast>"]

        while self._running:
            try:
                for addr in broadcasts:
                    try:
                        sock.sendto(data, (addr, UDP_PORT))
                    except Exception:
                        pass
            except OSError:
                pass
            time.sleep(BROADCAST_INTERVAL)

        sock.close()

    def _listener_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass

        try:
            sock.bind(("", UDP_PORT))
        except Exception:
            return

        sock.settimeout(2)

        while self._running:
            try:
                raw, (sender_ip, _) = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                continue

            try:
                message = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue

            self._handle_beacon(message, sender_ip)

        sock.close()

    def _handle_beacon(self, message: str, sender_ip: str) -> None:
        """Parse a beacon message and update the known-peers dict."""
        parts = message.split(":")
        if len(parts) != 4 or parts[0] != "LANTERN_DISCOVER":
            return

        _, peer_id, hostname, tcp_port_str = parts

        if peer_id == self.peer_id:
            return

        try:
            tcp_port = int(tcp_port_str)
        except ValueError:
            return

        with self._lock:
            self._peers[peer_id] = {
                "ip": sender_ip,
                "hostname": hostname,
                "tcp_port": tcp_port,
                "last_seen": time.time(),
            }
