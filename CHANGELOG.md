# Changelog

All notable changes to Lantern are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Security
- Removed remote file deletion — any peer on the LAN could previously wipe
  another peer's files with no authentication or confirmation.
- Added 64 KB cap on incoming control messages to prevent memory exhaustion
  from a malicious peer sending a forged length prefix.
- Capped concurrent server connections at 50 to prevent thread exhaustion.
- Server no longer echoes raw client input or exception internals in error
  responses, preventing information leakage.
- Download path now sanitized with `os.path.basename`; a malicious server
  can no longer write files outside the shared directory via path traversal.
- `_safe_filename` hardened to strip null bytes, reject `..`, and block
  Windows reserved names (CON, NUL, COM1–COM9, LPT1–LPT9).
- Beacon parser now validates TCP port range (1–65535) and handles hostnames
  containing colons without corrupting the parsed fields.
- Untrusted peer hostnames and filenames are now escaped before being
  rendered in the TUI, preventing Rich markup injection.

### Fixed
- Shared directory is now a stable path (`~/Downloads/Lantern`) instead of a
  new timestamped folder created on every launch.
- Invalid port strings (e.g. `list host:notaport`) no longer crash the CLI
  or TUI command input — a clear error message is shown instead.
- `__init__.py` still exported `do_delete` after it was removed from
  `client.py`; corrected.
- Server upload handler now uses the shared `recv_file` helper from
  `protocol.py` instead of a duplicated raw receive loop.
- `recv_file` now deletes the partial file if the transfer is cancelled or
  the connection drops, leaving no corrupt data in the shared directory.
- `_connect` socket is now closed if `connect()` raises, fixing a FD leak.
- Server socket is now closed if `bind()` or `listen()` raises.
- `psutil` returning `None` for a network interface netmask no longer causes
  an `AttributeError` in `get_broadcast_addresses`.
- `--port` CLI argument now validates the range 1–65535.
- TUI `CSS_PATH` now uses the absolute path resolved at import time so the
  stylesheet loads correctly after `pip install`.
- `__version__` in `__init__.py` updated to match `pyproject.toml` (1.0.3).

### Added
- 17-test suite covering `protocol.py` (message framing, file transfer,
  progress callbacks, cancellation) and `client.py` (`format_size`).
- Security notice in README warning users not to run Lantern on untrusted
  networks.

---

## [1.0.3] — 2026-02-20

### Added
- Progress bar modal for file transfers with cancel support.
- Download timeout and progress callback support in the client.

---

## [1.0.2] — 2026-02-20

### Changed
- Shared directory moved to `~/Downloads/Lantern_<timestamp>/`
  (superseded in Unreleased by the stable path fix).

### Added
- ASCII art logo in README.

---

## [1.0.1] — 2026-02-19

### Added
- GitHub Actions workflow for automatic PyPI publishing on release.
- TUI set as the default mode; `--cli` flag added for the text interface.
- Pip-installable package structure (`pyproject.toml`, entry point).

### Fixed
- License field format corrected for PyPI upload.
