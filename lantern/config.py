"""
Configuration constants for the P2P file sharing system.
"""

import os
import uuid

# --- Networking ---
TCP_PORT = 5000  # Default TCP port for file operations
UDP_PORT = 5001  # UDP port for peer discovery broadcasts
BUFFER_SIZE = (
    65536  # Chunk size (bytes) for file transfer (64 KB for better LAN throughput)
)
BROADCAST_INTERVAL = 5  # Seconds between UDP discovery beacons
PEER_TIMEOUT = 15  # Seconds before a peer is considered offline

# --- Protocol ---
SEPARATOR = "<SEP>"  # Delimiter used in protocol messages

# --- File Storage ---
# Stored inside Downloads so users can easily find and access shared files.
SHARED_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "Lantern")

# --- Identity ---
# Each peer gets a unique ID at startup so it can ignore its own broadcasts
PEER_ID = str(uuid.uuid4())[:8]
