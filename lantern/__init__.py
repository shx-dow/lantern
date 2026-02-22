"""
Lantern - P2P File Sharing System

A peer-to-peer file sharing application with a beautiful TUI dashboard.
"""

__version__ = "1.1.0"
__author__ = "shx-dow"

from .config import (
    TCP_PORT,
    UDP_PORT,
    BUFFER_SIZE,
    BROADCAST_INTERVAL,
    PEER_TIMEOUT,
    SEPARATOR,
    SHARED_DIR,
    PEER_ID,
)
from .discovery import PeerDiscovery
from .server import FileServer
from .client import (
    fetch_file_list,
    do_download,
    do_upload_request,
    format_size,
)
from .protocol import send_msg, recv_msg, send_file, recv_file

__all__ = [
    "TCP_PORT",
    "UDP_PORT",
    "BUFFER_SIZE",
    "BROADCAST_INTERVAL",
    "PEER_TIMEOUT",
    "SEPARATOR",
    "SHARED_DIR",
    "PEER_ID",
    "PeerDiscovery",
    "FileServer",
    "fetch_file_list",
    "do_download",
    "do_upload_request",
    "format_size",
    "send_msg",
    "recv_msg",
    "send_file",
    "recv_file",
]
