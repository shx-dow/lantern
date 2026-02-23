"""
Lantern - P2P File Sharing System

A peer-to-peer file sharing application with a beautiful TUI dashboard.
"""

__version__ = "1.1.1"
__author__ = "shx-dow"

from .client import (
    do_download,
    do_upload_request,
    fetch_file_list,
    format_size,
)
from .config import (
    BROADCAST_INTERVAL,
    BUFFER_SIZE,
    PEER_ID,
    PEER_TIMEOUT,
    SEPARATOR,
    SHARED_DIR,
    TCP_PORT,
    UDP_PORT,
)
from .discovery import PeerDiscovery
from .protocol import recv_file, recv_msg, send_file, send_msg
from .server import FileServer

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
