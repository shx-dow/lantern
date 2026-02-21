# Changelog

All notable changes to Lantern are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Security
- Removed remote file deletion — any peer on the LAN could previously wipe
  another peer's files with no authentication or confirmation.
- Added 2 GB hard cap on incoming uploads to prevent disk exhaustion attacks.

### Fixed
- Shared directory is now a stable path (`~/Lantern/shared/`) instead of a
  new timestamped folder created on every launch.
- Invalid port strings (e.g. `list host:notaport`) no longer crash the CLI
  or TUI command input — a clear error message is shown instead.
- `__init__.py` still exported `do_delete` after it was removed from
  `client.py`; corrected.
- Server upload handler now uses the shared `recv_file` helper from
  `protocol.py` instead of a duplicated raw receive loop.

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
