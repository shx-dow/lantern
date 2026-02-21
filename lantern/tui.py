"""
Lantern TUI — A polished terminal dashboard for P2P file sharing.

Built with Textual.  Launched via `python peer.py --tui`.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import (
    Header,
    Footer,
    Static,
    DataTable,
    RichLog,
    Input,
    Button,
    Label,
    ListView,
    ListItem,
    ProgressBar,
)
from textual.screen import ModalScreen, Screen
from textual.reactive import reactive

from .config import TCP_PORT, SHARED_DIR, PEER_ID
from .discovery import PeerDiscovery
from .server import FileServer
from .client import (
    fetch_file_list,
    do_download,
    do_upload,
    format_size,
)


# Load CSS from external file
CSS_FILE = os.path.join(os.path.dirname(__file__), "styles", "lantern.css")


# ==============================================================================
# Transfer Progress Modal
# ==============================================================================


class TransferProgressScreen(ModalScreen):
    """Modal showing transfer progress with progress bar."""

    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(
        self,
        operation: str,
        filename: str,
        total_size: int,
        cancel_event: threading.Event = None,
    ):
        super().__init__()
        self.operation = operation
        self.filename = filename
        self.total_size = total_size
        self.current_size = 0
        self.cancel_event = cancel_event
        self._completed = False

    def compose(self) -> ComposeResult:
        with Container(id="upload-dialog"):
            yield Label(f"{self.operation}: {self.filename}", id="upload-title")
            yield Label(f"0 / {format_size(self.total_size)}", id="transfer-status")
            yield ProgressBar(total=self.total_size, id="progress-bar")
            yield Button("Cancel", variant="error", id="btn-cancel")

    def on_mount(self) -> None:
        pass

    def update_progress(self, current: int) -> None:
        """Update the progress bar and status."""
        if not self.is_mounted or self._completed:
            return
        try:
            self.current_size = current
            progress_bar = self.query_one("#progress-bar", ProgressBar)
            status_label = self.query_one("#transfer-status", Label)

            progress_bar.advance(current - progress_bar.progress)
            percent = (current / self.total_size * 100) if self.total_size > 0 else 100
            status_label.update(
                f"{format_size(current)} / {format_size(self.total_size)} ({percent:.1f}%)"
            )
        except Exception:
            pass

    def mark_complete(self, success: bool, message: str = None) -> None:
        """Mark transfer as complete and update UI."""
        self._completed = True
        try:
            cancel_btn = self.query_one("#btn-cancel", Button)
            if success:
                cancel_btn.label = "Close"
                cancel_btn.variant = "success"
                cancel_btn.id = "btn-close"
                if message:
                    status_label = self.query_one("#transfer-status", Label)
                    status_label.update(message)
            else:
                cancel_btn.label = "Close"
                cancel_btn.variant = "warning"
                cancel_btn.id = "btn-close"
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-cancel":
            if self.cancel_event:
                self.cancel_event.set()
            self.dismiss(False)
        elif btn_id == "btn-close":
            self.dismiss(True)

    def action_close(self) -> None:
        if self._completed:
            self.dismiss(True)
        elif self.cancel_event:
            self.cancel_event.set()
            self.dismiss(False)


# ==============================================================================
# Notification Widget
# ==============================================================================


class Notification(Static):
    """Toast notification widget."""

    DEFAULT_CSS = """
    Notification {
        dock: top;
        height: auto;
        padding: 1 2;
        margin: 1 4;
        opacity: 0;
        transition: opacity 0.3;
    }
    """

    def __init__(self, message: str, notification_type: str = "info"):
        super().__init__(message, id="notification-toast")
        self.notification_type = notification_type

    def on_mount(self) -> None:
        self.add_class(self.notification_type)
        self.add_class("visible")
        # Auto-hide after 3 seconds
        self.set_timer(3.0, self._hide)

    def _hide(self) -> None:
        self.remove_class("visible")
        self.set_timer(0.3, self.remove)


# ==============================================================================
# Help Modal
# ==============================================================================


class HelpScreen(ModalScreen):
    """Full help overlay."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Container(id="help-dialog"):
            yield Label("LANTERN  —  Help", id="help-title")
            yield Static(
                "[bold #5ec4ff]Keybindings[/]\n"
                "\n"
                "  [#e0c97f]F1[/]          Show this help\n"
                "  [#e0c97f]F5[/]          Refresh file list from selected peer\n"
                "  [#e0c97f]t[/]           Toggle theme (Lantern Dark / Light)\n"
                "  [#e0c97f]u[/]           Upload a file to the selected peer\n"
                "  [#e0c97f]d[/]           Download the selected file\n"
                "  [#e0c97f]Tab[/]         Cycle focus between panels\n"
                "  [#e0c97f]q[/]           Quit Lantern\n"
                "\n"
                "[bold #5ec4ff]Command Input[/]\n"
                "\n"
                "  Type commands in the bottom bar:\n"
                "  [#718ca1]list <host[:port]>[/]               List remote files\n"
                "  [#718ca1]download <host[:port]> <file>[/]    Download a file\n"
                "  [#718ca1]upload <host[:port]> <path>[/]      Upload a file\n"
                "  [#718ca1]peers[/]                            Show discovered peers\n"
                "  [#718ca1]myfiles[/]                          Refresh local files\n",
                id="help-content",
            )
            yield Button("Close  (Esc)", id="help-close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close-btn":
            self.dismiss()


# ==============================================================================
# Upload Modal
# ==============================================================================


class UploadScreen(ModalScreen[str | None]):
    """Modal dialog to enter a file path for uploading."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container(id="upload-dialog"):
            yield Label("Upload File", id="upload-title")
            yield Input(placeholder="Enter file path...", id="upload-input")
            with Horizontal(id="upload-btn-bar"):
                yield Button("Upload", variant="success", id="upload-confirm")
                yield Button("Cancel", variant="error", id="upload-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "upload-confirm":
            inp = self.query_one("#upload-input", Input)
            self.dismiss(inp.value.strip() or None)
        elif event.button.id == "upload-cancel":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ==============================================================================
# Loading Screen
# ==============================================================================


class LoadingScreen(Screen):
    """Simple loading screen with just the logo."""

    BINDINGS = [
        Binding("enter", "dismiss", ""),
        Binding("space", "dismiss", ""),
        Binding("escape", "dismiss", ""),
    ]

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold #EBD5AB] _             _                [/]\n"
            "[bold #EBD5AB]| |   __ _ _ _| |_ ___ _ _ _ _  [/]\n"
            "[bold #EBD5AB]| |__/ _` | ' \\  _/ -_) '_| ' \\ [/]\n"
            "[bold #EBD5AB]|____\\__,_|_||_\\__\\___|_| |_||_|[/]",
            id="loading-logo",
        )

    def on_mount(self) -> None:
        # Auto-dismiss after 2 seconds
        self.set_timer(2.0, self.action_dismiss)

    def on_key(self, event) -> None:
        # Dismiss on any key press immediately
        if self.is_mounted:
            self.action_dismiss()

    def action_dismiss(self) -> None:
        """Dismiss the loading screen safely."""
        if self.is_mounted:
            self.app.pop_screen()


# ==============================================================================
# Main TUI App
# ==============================================================================


class LanternApp(App):
    """Lantern P2P File Sharing — Terminal Dashboard."""

    TITLE = "LANTERN"
    SUB_TITLE = "P2P File Sharing"
    CSS_PATH = "styles/lantern.css"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("f1", "show_help", "Help", show=True),
        Binding("f5", "refresh_files", "Refresh", show=True),
        Binding("t", "toggle_app_theme", "Theme", show=True),
        Binding("u", "upload_file", "Upload", show=True),
        Binding("d", "download_file", "Download", show=True),
        Binding("q", "quit_app", "Quit", show=True),
    ]

    # -- reactive state --
    selected_peer: reactive[dict | None] = reactive(None)
    dark_theme: reactive[bool] = reactive(True)
    remote_files: reactive[list[dict]] = reactive([])

    def __init__(
        self,
        discovery: PeerDiscovery,
        file_server: FileServer,
        tcp_port: int = TCP_PORT,
    ):
        super().__init__()
        self.discovery = discovery
        self.file_server = file_server
        self.tcp_port = tcp_port
        self.theme = "textual-dark"

    # --------------------------------------------------------------------------
    # Layout
    # --------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main-container"):
            # ── Sidebar ──
            with Vertical(id="sidebar"):
                yield Label("PEERS", id="sidebar-title")
                with Container(id="peer-list-container"):
                    yield ListView(id="peer-list")
                yield Label("MY FILES", id="my-files-title")
                yield DataTable(id="my-files-table")

            # ── Main panel ──
            with Vertical(id="main-panel"):
                with Container(id="files-header"):
                    yield Label(
                        "Select a peer to view files",
                        id="files-header-text",
                    )
                yield DataTable(id="remote-files-table")

                # Action buttons
                with Horizontal(id="action-bar"):
                    yield Button("Upload", id="btn-upload")
                    yield Button("Download", id="btn-download")
                    yield Button("Refresh", id="btn-refresh")

        # ── Log panel ──
        with Vertical(id="log-panel"):
            yield Label(" LOG", id="log-title")
            yield RichLog(id="log-view", highlight=True, markup=True)

        # ── Command input ──
        with Horizontal(id="command-bar"):
            yield Input(
                placeholder="Type a command (or press F1 for help)...",
                id="command-input",
            )

        yield Footer()

    # --------------------------------------------------------------------------
    # Startup
    # --------------------------------------------------------------------------

    def on_mount(self) -> None:
        self._setup_tables()
        self._refresh_my_files()

        # Periodic refresh timers
        self.set_interval(3.0, self._poll_peers)
        self.set_interval(10.0, self._refresh_my_files)

        # Log startup info
        self._log(
            f"Lantern started  [bold #5ec4ff]peer_id={PEER_ID}[/]  tcp_port={self.tcp_port}"
        )
        self._log(f"Shared directory: [#718ca1]{SHARED_DIR}[/]")
        self._log("Discovering peers on the network...")

        # Show loading screen first - logs will appear after it's dismissed
        self.push_screen(LoadingScreen())

    def _setup_tables(self) -> None:
        # My files table
        my_table = self.query_one("#my-files-table", DataTable)
        my_table.add_columns("File", "Size")
        my_table.cursor_type = "row"
        my_table.zebra_stripes = True

        # Remote files table
        remote_table = self.query_one("#remote-files-table", DataTable)
        remote_table.add_columns("Filename", "Size")
        remote_table.cursor_type = "row"
        remote_table.zebra_stripes = True

    # --------------------------------------------------------------------------
    # Logging & Notifications
    # --------------------------------------------------------------------------

    def _log(self, message: str) -> None:
        log_view = self.query_one("#log-view", RichLog)
        ts = datetime.now().strftime("%H:%M:%S")
        log_view.write(f"[#41505e]{ts}[/]  {message}")

    def show_notification(self, message: str, notification_type: str = "info") -> None:
        """Show a toast notification."""
        notification = Notification(message, notification_type)
        self.mount(notification)

    # --------------------------------------------------------------------------
    # Peer discovery polling
    # --------------------------------------------------------------------------

    def _poll_peers(self) -> None:
        peers = self.discovery.get_peers()
        peer_list = self.query_one("#peer-list", ListView)

        # Build a set of current peer IDs for comparison
        current_ids = {p["peer_id"] for p in peers}

        # Check if the list actually changed
        existing_items = list(peer_list.children)
        existing_ids = set()
        for item in existing_items:
            pid = getattr(item, "peer_data_id", None)
            if pid:
                existing_ids.add(pid)

        if current_ids == existing_ids:
            return  # No change

        # Log new peers
        for p in peers:
            if p["peer_id"] not in existing_ids:
                self._log(
                    f"[#00ff9f]Discovered[/] peer "
                    f"[bold #5ec4ff]{p['hostname']}[/] "
                    f"([#718ca1]{p['ip']}:{p['tcp_port']}[/])"
                )

        # Log lost peers
        for pid in existing_ids - current_ids:
            self._log(f"[#e74c3c]Lost[/] peer [#718ca1]{pid}[/]")

        # Rebuild the list
        peer_list.clear()
        for p in peers:
            label = Static(
                f"[#00ff9f]●[/] [bold #5ec4ff]{p['hostname']}[/]\n"
                f"  [#718ca1]{p['ip']}:{p['tcp_port']}[/]",
                classes="peer-entry",
            )
            item = ListItem(label)
            item.peer_data_id = p["peer_id"]  # type: ignore[attr-defined]
            item.peer_data = p  # type: ignore[attr-defined]
            peer_list.append(item)

    # --------------------------------------------------------------------------
    # Peer selection
    # --------------------------------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        peer = getattr(item, "peer_data", None)
        if peer:
            self.selected_peer = peer
            header_label = self.query_one("#files-header-text", Label)
            header_label.update(
                f"FILES ON: [bold #5ec4ff]{peer['hostname']}[/]  "
                f"([#718ca1]{peer['ip']}:{peer['tcp_port']}[/])"
            )
            self._refresh_remote_files()

    # --------------------------------------------------------------------------
    # File listing refresh
    # --------------------------------------------------------------------------

    def _refresh_my_files(self) -> None:
        table = self.query_one("#my-files-table", DataTable)
        table.clear()
        os.makedirs(SHARED_DIR, exist_ok=True)
        for name in sorted(os.listdir(SHARED_DIR)):
            filepath = os.path.join(SHARED_DIR, name)
            if os.path.isfile(filepath):
                size = os.path.getsize(filepath)
                table.add_row(name, format_size(size))

    @work(thread=True)
    def _refresh_remote_files(self) -> None:
        peer = self.selected_peer
        if not peer:
            return

        try:
            files = fetch_file_list(peer["ip"], peer["tcp_port"])
            self.app.call_from_thread(self._update_remote_table, files)
        except Exception as e:
            self.app.call_from_thread(
                self._log,
                f"[#e74c3c]Error[/] listing files from "
                f"[#5ec4ff]{peer['hostname']}[/]: {e}",
            )

    def _update_remote_table(self, files: list[dict]) -> None:
        self.remote_files = files
        table = self.query_one("#remote-files-table", DataTable)
        table.clear()
        for f in files:
            table.add_row(f["name"], format_size(f["size"]))

    # --------------------------------------------------------------------------
    # Actions — keybindings
    # --------------------------------------------------------------------------

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_toggle_app_theme(self) -> None:
        self.dark_theme = not self.dark_theme
        if self.dark_theme:
            self.theme = "textual-dark"
            self.remove_class("app-light")
            self._log("[#e0c97f]Theme:[/] Lantern Dark")
        else:
            self.theme = "textual-light"
            self.add_class("app-light")
            self._log("[#e0c97f]Theme:[/] Lantern Light")

    def action_quit_app(self) -> None:
        self._log("Shutting down...")
        self.exit()

    def action_refresh_files(self) -> None:
        self._refresh_my_files()
        if self.selected_peer:
            self._refresh_remote_files()
            self._log(
                f"Refreshing files from [#5ec4ff]{self.selected_peer['hostname']}[/]..."
            )
        else:
            self._log("No peer selected — refreshed local files only.")

    def action_upload_file(self) -> None:
        if not self.selected_peer:
            self._log("[#e0c97f]Warning:[/] Select a peer first before uploading.")
            return
        self.push_screen(UploadScreen(), callback=self._handle_upload_result)

    def _handle_upload_result(self, filepath: str | None) -> None:
        if filepath is None:
            return
        peer = self.selected_peer
        if not peer:
            return
        self._do_upload_async(peer, filepath)

    @work(thread=True)
    def _do_upload_async(self, peer: dict, filepath: str) -> None:
        self.app.call_from_thread(
            self._log,
            f"Uploading [bold]{os.path.basename(filepath)}[/] to "
            f"[#5ec4ff]{peer['hostname']}[/]...",
        )

        progress_screen = None
        filesize = os.path.getsize(filepath)
        if filesize > 1024 * 1024:
            cancel_event = threading.Event()

            def show_progress():
                nonlocal progress_screen
                progress_screen = TransferProgressScreen(
                    "Upload", os.path.basename(filepath), filesize, cancel_event
                )
                self.push_screen(progress_screen)

            self.app.call_from_thread(show_progress)

        try:
            msg = do_upload(peer["ip"], peer["tcp_port"], filepath)

            if progress_screen:
                self.app.call_from_thread(
                    progress_screen.mark_complete,
                    True,
                    f"Complete: {format_size(filesize)}",
                )

            self.app.call_from_thread(
                self._log,
                f"[#00ff9f]Success:[/] {msg}",
            )
            self.app.call_from_thread(
                self.show_notification,
                f"Uploaded {os.path.basename(filepath)}",
                "success",
            )
            self.app.call_from_thread(self._refresh_my_files)
            self._refresh_remote_files()
        except Exception as e:
            if progress_screen:
                self.app.call_from_thread(progress_screen.mark_complete, False, str(e))
            self.app.call_from_thread(
                self._log,
                f"[#e74c3c]Upload failed:[/] {e}",
            )
            self.app.call_from_thread(
                self.show_notification,
                f"Upload failed: {e}",
                "error",
            )

    def action_download_file(self) -> None:
        if not self.selected_peer:
            self._log("[#e0c97f]Warning:[/] Select a peer first.")
            return

        table = self.query_one("#remote-files-table", DataTable)
        if table.row_count == 0:
            self._log("[#e0c97f]Warning:[/] No files to download.")
            return

        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            row_data = table.get_row(row_key)
            filename = row_data[0]
        except Exception:
            self._log("[#e0c97f]Warning:[/] Select a file in the table first.")
            return

        filesize = None
        for f in self.remote_files:
            if f["name"] == filename:
                filesize = f["size"]
                break

        peer = self.selected_peer
        self._do_download_async(peer, filename, filesize)

    @work(thread=True)
    def _do_download_async(
        self, peer: dict, filename: str, filesize: int = None
    ) -> None:
        self.app.call_from_thread(
            self._log,
            f"Downloading [bold]{filename}[/] from [#5ec4ff]{peer['hostname']}[/]...",
        )

        progress_screen = None
        cancel_event = None

        if filesize and filesize > 1024 * 1024:
            cancel_event = threading.Event()

            def show_progress():
                nonlocal progress_screen
                progress_screen = TransferProgressScreen(
                    "Download", filename, filesize, cancel_event
                )
                self.push_screen(progress_screen)

            self.app.call_from_thread(show_progress)

        def progress_callback(current: int, total: int):
            if progress_screen:
                self.app.call_from_thread(progress_screen.update_progress, current)

        try:
            dest, received = do_download(
                peer["ip"],
                peer["tcp_port"],
                filename,
                progress_callback,
                cancel_event,
            )
            if progress_screen:
                self.app.call_from_thread(
                    progress_screen.mark_complete,
                    True,
                    f"Complete: {format_size(received)}",
                )
            self.app.call_from_thread(
                self._log,
                f"[#00ff9f]Downloaded[/] {filename} "
                f"({format_size(received)}) -> [#718ca1]{dest}[/]",
            )
            self.app.call_from_thread(
                self.show_notification,
                f"Downloaded {filename}",
                "success",
            )
            self.app.call_from_thread(self._refresh_my_files)
        except Exception as e:
            if progress_screen:
                self.app.call_from_thread(progress_screen.mark_complete, False, str(e))
            self.app.call_from_thread(
                self._log,
                f"[#e74c3c]Download failed:[/] {e}",
            )
            self.app.call_from_thread(
                self.show_notification,
                f"Download failed: {e}",
                "error",
            )

    # --------------------------------------------------------------------------
    # Button handlers
    # --------------------------------------------------------------------------
    # Button handlers
    # --------------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-upload":
            self.action_upload_file()
        elif btn_id == "btn-download":
            self.action_download_file()
        elif btn_id == "btn-refresh":
            self.action_refresh_files()

    # --------------------------------------------------------------------------
    # Command input
    # --------------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "command-input":
            return

        raw = event.value.strip()
        event.input.value = ""
        if not raw:
            return

        tokens = raw.split()
        cmd = tokens[0].lower()

        if cmd == "help":
            self.action_show_help()
        elif cmd == "peers":
            self._cmd_peers()
        elif cmd == "myfiles":
            self._refresh_my_files()
            self._log("Refreshed local file list.")
        elif cmd == "list" and len(tokens) >= 2:
            host, port = self._parse_target(tokens[1])
            self._cmd_list(host, port)
        elif cmd == "download" and len(tokens) >= 3:
            host, port = self._parse_target(tokens[1])
            self._do_download_async(
                {"ip": host, "tcp_port": port, "hostname": host}, tokens[2]
            )
        elif cmd == "upload" and len(tokens) >= 3:
            host, port = self._parse_target(tokens[1])
            self._do_upload_async(
                {"ip": host, "tcp_port": port, "hostname": host}, tokens[2]
            )
        elif cmd in ("quit", "exit"):
            self.action_quit_app()
        else:
            self._log(f"[#e0c97f]Unknown command:[/] {raw}  (press F1 for help)")

    def _parse_target(self, target: str) -> tuple[str, int]:
        if ":" in target:
            host, port_str = target.rsplit(":", 1)
            return host, int(port_str)
        return target, self.tcp_port

    def _cmd_peers(self) -> None:
        peers = self.discovery.get_peers()
        if not peers:
            self._log("No peers discovered yet.")
        else:
            for p in peers:
                self._log(
                    f"  [#00ff9f]●[/] [bold #5ec4ff]{p['hostname']}[/]  "
                    f"[#718ca1]{p['ip']}:{p['tcp_port']}[/]"
                )

    @work(thread=True)
    def _cmd_list(self, host: str, port: int) -> None:
        try:
            files = fetch_file_list(host, port)
            if not files:
                self.app.call_from_thread(
                    self._log, f"No files on [#718ca1]{host}:{port}[/]"
                )
            else:
                for f in files:
                    self.app.call_from_thread(
                        self._log,
                        f"  {f['name']}  [#718ca1]{format_size(f['size'])}[/]",
                    )
        except Exception as e:
            self.app.call_from_thread(
                self._log,
                f"[#e74c3c]Error:[/] {e}",
            )


# ==============================================================================
# Entry point (called from peer.py)
# ==============================================================================


def run_tui(discovery: PeerDiscovery, file_server: FileServer, tcp_port: int) -> None:
    """Launch the Lantern TUI."""
    app = LanternApp(discovery, file_server, tcp_port)
    app.run()
