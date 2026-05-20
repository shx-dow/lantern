import os
import uuid

TCP_PORT = 5000
UDP_PORT = 5001
BUFFER_SIZE = 65536
BROADCAST_INTERVAL = 5
PEER_TIMEOUT = 15
SEPARATOR = "<SEP>"
SHARED_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "Lantern")
SHOW_WELCOME_SCREEN = os.getenv("LANTERN_SHOW_WELCOME", "1").lower() not in {
    "0",
    "false",
    "no",
}
PEER_ID = str(uuid.uuid4())[:8]
