"""
Configuration constants for the P2P file sharing system.
"""

import os
import uuid

# --- Networking ---
TCP_PORT = 5000              # Default TCP port for file operations
UDP_PORT = 5001              # UDP port for peer discovery broadcasts
BUFFER_SIZE = 4096           # Chunk size (bytes) for file transfer
BROADCAST_INTERVAL = 5       # Seconds between UDP discovery beacons
PEER_TIMEOUT = 15            # Seconds before a peer is considered offline

# --- Protocol ---
SEPARATOR = "<SEP>"          # Delimiter used in protocol messages

# --- File Storage ---
SHARED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared_files")

# --- Identity ---
# Each peer gets a unique ID at startup so it can ignore its own broadcasts
PEER_ID = str(uuid.uuid4())[:8]
