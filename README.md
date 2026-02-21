```
 _             _                
| |   __ _ _ _| |_ ___ _ _ _ _  
| |__/ _` | ' \  _/ -_) '_| ' \ 
|____\__,_|_||_\__\___|_| |_||_|
```

A peer-to-peer file sharing system with a beautiful terminal UI (TUI) dashboard.

![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## Features

- **P2P File Sharing** - Share files directly between computers on the same network
- **Auto Discovery** - Automatically discovers peers on the LAN via UDP broadcast
- **Beautiful TUI** - Modern terminal interface built with Textual
- **Dual Mode** - Both CLI and TUI modes available
- **Light/Dark Themes** - Toggle between color schemes
- **Progress Bars** - Visual feedback for large file transfers
- **Notifications** - Toast notifications for operation completion
- **Path Safety** - Built-in protection against path traversal attacks

## Installation

### From PyPI (when published)

```bash
pip install lantern-p2p
```

### From Source

```bash
git clone https://github.com/shx-dow/lantern.git
cd lantern
pip install -e .
```

## Usage

### TUI Mode (Default)

Launch the terminal dashboard (beautiful visual interface):

```bash
lantern
```

### CLI Mode

Use command-line interface (text-based commands):

```bash
lantern --cli
```

Available CLI commands:
- `peers` - Show discovered peers
- `list <host[:port]>` - List files on remote peer
- `download <host[:port]> <file>` - Download a file
- `upload <host[:port]> <path>` - Upload a file
- `myfiles` - List your shared files
- `help` - Show help
- `quit` - Exit

### Custom Port

```bash
lantern --port 6000
```

## Key Bindings (TUI Mode)

| Key | Action |
|-----|--------|
| `F1` | Show help |
| `F5` | Refresh files |
| `t` | Toggle theme |
| `u` | Upload file |
| `d` | Download file |
| `Tab` | Cycle focus |
| `q` | Quit |

## Configuration

Shared files are stored in `~/Lantern/shared/` by default. This directory is created automatically on first run and persists across restarts.

## Security Notice

Lantern is designed for **trusted local area networks only** (e.g. your home network). It has no encryption and no peer authentication.

- **Do not run Lantern on public or untrusted networks** (coffee shops, offices, university Wi-Fi, etc.). Anyone on the same network can see your shared files and upload arbitrary content to your machine.
- The shared directory is world-readable by any Lantern peer on the LAN — only share files you are comfortable with all LAN participants seeing.

## Requirements

- Python 3.10 or higher
- textual >= 0.50.0
- psutil >= 5.9.0

## Architecture

```
lantern/
├── config.py      # Configuration constants
├── protocol.py    # Message framing & file transfer protocol
├── discovery.py   # UDP peer discovery
├── server.py      # TCP file server
├── client.py      # TCP client operations
├── peer.py        # CLI entry point
├── tui.py         # Textual TUI dashboard
├── main.py        # Package entry point
└── styles/        # CSS stylesheets
    └── lantern.css
```

## Development

Install with dev dependencies:

```bash
pip install -e ".[dev]"
```

Run linting:

```bash
black lantern/
ruff check lantern/
```

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions welcome! Please open an issue or pull request.

## Acknowledgments

Built with [Textual](https://textual.textualize.io/) for the TUI.
