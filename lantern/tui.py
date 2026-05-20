"""Textual interface for Lantern."""

from __future__ import annotations

import os
import queue
import threading
from datetime import datetime
from pathlib import Path

from rich.markup import escape as markup_escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    RichLog,
    Static,
)
from textual_fspicker import FileOpen

from .client import (
    do_download,
    do_upload_request,
    fetch_file_list,
    format_size,
)
from .config import PEER_ID, SHARED_DIR, SHOW_WELCOME_SCREEN, TCP_PORT
from .discovery import PeerDiscovery
from .server import FileServer, UploadRequest

CSS_FILE = os.path.join(os.path.dirname(__file__), "styles", "lantern.css")
CLASSIC_LOGO = (
    " _             _                \n"
    "| |   __ _ _ _| |_ ___ _ _ _ _  \n"
    "| |__/ _` | ' \\  _/ -_) '_| ' \\ \n"
    "|____\\__,_|_||_\\__\\___|_| |_||_|"
)


class TransferProgressScreen(ModalScreen):
    """Shows live progress for a file transfer."""

    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(
        self,
        operation: str,
        filename: str,
        total_size: int,
        cancel_event: threading.Event | None = None,
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

    def mark_complete(self, success: bool, message: str | None = None) -> None:
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


class Notification(Static):
    """Small toast message."""

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
        self.set_timer(3.0, self._hide)

    def _hide(self) -> None:
        self.remove_class("visible")
        self.set_timer(0.3, self.remove)


class HelpScreen(ModalScreen):
    """Short in-app guide."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, dark: bool = True):
        super().__init__()
        self._dark = dark

    def compose(self) -> ComposeResult:
        if self._dark:
            heading = "#5dba6e"
            keybind = "#c4944a"
            cmd = "#7090a0"
        else:
            heading = "#3d8b7d"
            keybind = "#7a5c00"
            cmd = "#4a6878"

        with Container(id="help-dialog"):
            yield Label("Lantern help", id="help-title")
            yield Static(
                f"[bold {heading}]Getting started[/]\n"
                "\n"
                "  1. Run Lantern on another computer on this same network.\n"
                "  2. Select that computer from the Peers list.\n"
                "  3. Use Send file or Get selected to transfer files.\n"
                "\n"
                f"[bold {heading}]Keys[/]\n"
                "\n"
                f"  [{keybind}]F1[/]     Help\n"
                f"  [{keybind}]F5[/]     Refresh the selected peer\n"
                f"  [{keybind}]t[/]      Toggle theme\n"
                f"  [{keybind}]u[/]      Send a file\n"
                f"  [{keybind}]d[/]      Get the selected remote file\n"
                f"  [{keybind}]q[/]      Quit\n"
                "\n"
                f"[bold {heading}]Commands[/]\n"
                "\n"
                f"  [{cmd}]list <host[:port]>[/]               List remote files\n"
                f"  [{cmd}]download <host[:port]> <file>[/]    Download a file\n"
                f"  [{cmd}]upload <host[:port]> <path>[/]      Upload a file\n"
                f"  [{cmd}]peers[/]                            Show discovered peers\n"
                f"  [{cmd}]myfiles[/]                          Refresh local files\n",
                id="help-content",
            )
            yield Button("Close  (Esc)", id="help-close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close-btn":
            self.dismiss()


class UploadConfirmScreen(ModalScreen[bool]):
    """Ask whether to accept an incoming upload."""

    BINDINGS = [Binding("escape", "reject", "Reject")]

    def __init__(self, request: UploadRequest):
        super().__init__()
        self.request = request

    def compose(self) -> ComposeResult:
        with Container(id="upload-dialog"):
            yield Label("Incoming file", id="upload-title")
            yield Static(
                f"[bold #5dba6e]{markup_escape(self.request.sender_ip)}[/] wants to send:\n\n"
                f"  [bold]{markup_escape(self.request.filename)}[/]  "
                f"[#7090a0]({format_size(self.request.filesize)})[/]",
                id="upload-confirm-info",
            )
            with Horizontal(id="upload-btn-bar"):
                yield Button("Accept", variant="success", id="upload-accept")
                yield Button("Reject", variant="error", id="upload-reject")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "upload-accept":
            self.dismiss(True)
        elif event.button.id == "upload-reject":
            self.dismiss(False)

    def action_reject(self) -> None:
        self.dismiss(False)


class WelcomeScreen(Screen):
    """A short branded loading screen."""

    BINDINGS = [
        Binding("enter", "continue", "Start"),
        Binding("space", "continue", "Start"),
        Binding("escape", "continue", "Skip"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(CLASSIC_LOGO, id="welcome-logo")

    def on_mount(self) -> None:
        self.set_timer(1.5, self.action_continue)

    def action_continue(self) -> None:
        if self.is_mounted:
            self.app.pop_screen()


class LanternApp(App):
    """Lantern's terminal dashboard."""

    TITLE = "LANTERN"
    SUB_TITLE = "P2P File Sharing"
    CSS_PATH = CSS_FILE
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("f1", "show_help", "Help", show=True),
        Binding("f5", "refresh_files", "Refresh", show=True),
        Binding("t", "toggle_app_theme", "Theme", show=True),
        Binding("u", "upload_file", "Upload", show=True),
        Binding("d", "download_file", "Download", show=True),
        Binding("q", "quit_app", "Quit", show=True),
    ]

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

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main-container"):
            with Vertical(id="sidebar"):
                yield Label("PEERS", id="sidebar-title")
                yield Static("Looking for nearby Lantern apps...", id="peers-hint")
                with Container(id="peer-list-container"):
                    yield ListView(id="peer-list")
                yield Label("MY FILES", id="my-files-title")
                yield DataTable(id="my-files-table")

            with Vertical(id="main-panel"):
                with Container(id="files-header"):
                    yield Label(
                        "Waiting for another Lantern app",
                        id="files-header-text",
                    )
                yield Static(
                    "[bold #5dba6e]Start here[/]\n\n"
                    "Run Lantern on another computer connected to this network.\n"
                    "When it appears in Peers, select it to browse files.\n\n"
                    f"Files you receive are saved in:\n[#7090a0]{markup_escape(SHARED_DIR)}[/]\n\n"
                    "Trusted networks only: Lantern does not encrypt or authenticate peers.",
                    id="empty-state",
                )
                yield DataTable(id="remote-files-table")

                with Horizontal(id="action-bar"):
                    yield Button("Send file", id="btn-upload", disabled=True)
                    yield Button("Get selected", id="btn-download", disabled=True)
                    yield Button("Refresh list", id="btn-refresh", disabled=True)

        with Vertical(id="log-panel"):
            yield Label("ACTIVITY", id="log-title")
            yield RichLog(id="log-view", highlight=True, markup=True)

        with Horizontal(id="command-bar"):
            yield Input(
                placeholder="Optional command line. Press F1 for help.",
                id="command-input",
            )

        yield Footer()

    def on_mount(self) -> None:
        self._setup_tables()
        self._refresh_my_files()

        self.set_interval(3.0, self._poll_peers)
        self.set_interval(10.0, self._refresh_my_files)
        self.set_interval(0.5, self._poll_upload_requests)

        self._log(
            f"Lantern started  [bold #5dba6e]peer_id={PEER_ID}[/]  tcp_port={self.tcp_port}"
        )
        self._log(f"Shared directory: [#7090a0]{SHARED_DIR}[/]")
        self._log("Looking for peers on this local network...")

        if SHOW_WELCOME_SCREEN:
            self.push_screen(WelcomeScreen())

    def _setup_tables(self) -> None:
        my_table = self.query_one("#my-files-table", DataTable)
        my_table.add_columns("File", "Size")
        my_table.cursor_type = "row"
        my_table.zebra_stripes = True

        remote_table = self.query_one("#remote-files-table", DataTable)
        remote_table.add_columns("Filename", "Size")
        remote_table.cursor_type = "row"
        remote_table.zebra_stripes = True
        remote_table.display = False

    def _log(self, message: str) -> None:
        log_view = self.query_one("#log-view", RichLog)
        ts = datetime.now().strftime("%H:%M:%S")
        log_view.write(f"[#506050]{ts}[/]  {message}")

    def show_notification(self, message: str, notification_type: str = "info") -> None:
        notification = Notification(message, notification_type)
        self.mount(notification)

    def _poll_peers(self) -> None:
        peers = self.discovery.get_peers()
        peer_list = self.query_one("#peer-list", ListView)

        current_ids = {p["peer_id"] for p in peers}

        existing_items = list(peer_list.children)
        existing_ids = set()
        for item in existing_items:
            pid = getattr(item, "peer_data_id", None)
            if pid:
                existing_ids.add(pid)

        if current_ids == existing_ids:
            return

        for p in peers:
            if p["peer_id"] not in existing_ids:
                self._log(
                    f"[#5dba6e]Discovered[/] peer "
                    f"[bold #5dba6e]{markup_escape(p['hostname'])}[/] "
                    f"([#7090a0]{markup_escape(p['ip'])}:{p['tcp_port']}[/])"
                )

        for pid in existing_ids - current_ids:
            self._log(f"[#c26068]Lost[/] peer [#7090a0]{pid}[/]")

        peer_list.clear()
        self.query_one("#peers-hint", Static).display = not bool(peers)
        for p in peers:
            label = Static(
                f"[#5dba6e]●[/] [bold #5dba6e]{markup_escape(p['hostname'])}[/]\n"
                f"  [#7090a0]{markup_escape(p['ip'])}:{p['tcp_port']}[/]",
                classes="peer-entry",
            )
            item = ListItem(label)
            item.peer_data_id = p["peer_id"]  # type: ignore[attr-defined]
            item.peer_data = p  # type: ignore[attr-defined]
            peer_list.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        peer = getattr(item, "peer_data", None)
        if peer:
            self.selected_peer = peer
            self._set_peer_actions_enabled(True)
            header_label = self.query_one("#files-header-text", Label)
            header_label.update(
                f"FILES ON: [bold #5dba6e]{markup_escape(peer['hostname'])}[/]  "
                f"([#7090a0]{markup_escape(peer['ip'])}:{peer['tcp_port']}[/])"
            )
            self.query_one("#empty-state", Static).display = False
            self.query_one("#remote-files-table", DataTable).display = True
            self._refresh_remote_files()

    def _set_peer_actions_enabled(self, enabled: bool) -> None:
        for button_id in ("#btn-upload", "#btn-download", "#btn-refresh"):
            self.query_one(button_id, Button).disabled = not enabled

    def _poll_upload_requests(self) -> None:
        try:
            request = self.file_server.pending_uploads.get_nowait()
        except queue.Empty:
            return
        self._log(
            f"[#c4944a]Incoming upload request[/] from "
            f"[bold #5dba6e]{markup_escape(request.sender_ip)}[/]: "
            f"[bold]{markup_escape(request.filename)}[/] "
            f"([#7090a0]{format_size(request.filesize)}[/])"
        )
        self.push_screen(
            UploadConfirmScreen(request),
            callback=lambda accepted: self._handle_upload_confirm(
                request, accepted or False
            ),
        )

    def _handle_upload_confirm(self, request: UploadRequest, accepted: bool) -> None:
        if accepted:
            self._log(
                f"[#5dba6e]Accepted[/] upload of "
                f"[bold]{markup_escape(request.filename)}[/] from "
                f"[#5dba6e]{markup_escape(request.sender_ip)}[/]"
            )

            if request.filesize > 1024 * 1024:
                progress_screen = TransferProgressScreen(
                    "Receiving", request.filename, request.filesize
                )
                self.push_screen(progress_screen)

                def progress_callback(current: int, total: int) -> None:
                    self.call_from_thread(progress_screen.update_progress, current)

                def _watch_completion() -> None:
                    request.transfer_done_event.wait()
                    if request.transfer_success:
                        self.call_from_thread(
                            progress_screen.mark_complete,
                            True,
                            f"Complete: {format_size(request.filesize)}",
                        )
                        self.call_from_thread(
                            self.show_notification,
                            f"Received {request.filename}",
                            "success",
                        )
                    else:
                        self.call_from_thread(
                            progress_screen.mark_complete, False, "Transfer incomplete"
                        )
                    self.call_from_thread(self._refresh_my_files)

                threading.Thread(target=_watch_completion, daemon=True).start()
                request.accept(progress_callback=progress_callback)
            else:
                def _notify_done() -> None:
                    request.transfer_done_event.wait()
                    if request.transfer_success:
                        self.call_from_thread(
                            self.show_notification,
                            f"Received {request.filename}",
                            "success",
                        )
                        self.call_from_thread(
                            self._log,
                            f"[#5dba6e]Received[/] [bold]{markup_escape(request.filename)}[/] "
                            f"({format_size(request.filesize)})",
                        )
                    self.call_from_thread(self._refresh_my_files)

                threading.Thread(target=_notify_done, daemon=True).start()
                request.accept()
        else:
            request.reject()
            self._log(
                f"[#c26068]Rejected[/] upload of "
                f"[bold]{markup_escape(request.filename)}[/] from "
                f"[#5dba6e]{markup_escape(request.sender_ip)}[/]"
            )

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
                f"[#c26068]Error[/] listing files from "
                f"[#5dba6e]{markup_escape(peer['hostname'])}[/]: {markup_escape(str(e))}",
            )

    def _update_remote_table(self, files: list[dict]) -> None:
        self.remote_files = files
        table = self.query_one("#remote-files-table", DataTable)
        table.clear()
        for f in files:
            table.add_row(f["name"], format_size(f["size"]))
        if not files and self.selected_peer:
            self._log("Selected peer is online, but it has no shared files yet.")

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen(dark=self.dark_theme))

    def action_toggle_app_theme(self) -> None:
        self.dark_theme = not self.dark_theme
        if self.dark_theme:
            self.theme = "textual-dark"
            self.remove_class("app-light")
            self._log("[#c4944a]Theme:[/] Lantern Dark")
        else:
            self.theme = "textual-light"
            self.add_class("app-light")
            self._log("[#7a5c00]Theme:[/] Lantern Light")

    def action_quit_app(self) -> None:
        self._log("Shutting down...")
        self.exit()

    def action_refresh_files(self) -> None:
        self._refresh_my_files()
        if self.selected_peer:
            self._refresh_remote_files()
            self._log(
                f"Refreshing files from [#5dba6e]{markup_escape(self.selected_peer['hostname'])}[/]..."
            )
        else:
            self._log("Select a peer first. Local files were refreshed.")

    def action_upload_file(self) -> None:
        if not self.selected_peer:
            self._log("[#c4944a]Select a peer first[/] before sending a file.")
            return
        self.push_screen(
            FileOpen(
                str(Path.home()),
                title="Select File to Upload",
            ),
            callback=self._handle_upload_result,
        )

    def _handle_upload_result(self, filepath: Path | None) -> None:
        if filepath is None:
            return
        peer = self.selected_peer
        if not peer:
            return
        self._do_upload_async(peer, str(filepath))

    @work(thread=True)
    def _do_upload_async(self, peer: dict, filepath: str) -> None:
        self.app.call_from_thread(
            self._log,
            f"Requesting upload of [bold]{markup_escape(os.path.basename(filepath))}[/] to "
            f"[#5dba6e]{markup_escape(peer['hostname'])}[/]...",
        )

        progress_screen = None
        cancel_event = threading.Event()
        filesize = os.path.getsize(filepath)

        if filesize > 1024 * 1024:

            def show_progress():
                nonlocal progress_screen
                progress_screen = TransferProgressScreen(
                    "Upload", os.path.basename(filepath), filesize, cancel_event
                )
                self.push_screen(progress_screen)

            self.app.call_from_thread(show_progress)

        def progress_callback(current: int, total: int):
            if progress_screen:
                self.app.call_from_thread(progress_screen.update_progress, current)

        try:
            msg = do_upload_request(
                peer["ip"],
                peer["tcp_port"],
                filepath,
                progress_callback,
                cancel_event,
            )

            if progress_screen:
                self.app.call_from_thread(
                    progress_screen.mark_complete,
                    True,
                    f"Complete: {format_size(filesize)}",
                )

            self.app.call_from_thread(
                self._log,
                f"[#5dba6e]Success:[/] {msg}",
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
                f"[#c26068]Upload failed:[/] {e}",
            )
            self.app.call_from_thread(
                self.show_notification,
                f"Upload failed: {e}",
                "error",
            )

    def action_download_file(self) -> None:
        if not self.selected_peer:
            self._log("[#c4944a]Select a peer first[/] before getting a file.")
            return

        table = self.query_one("#remote-files-table", DataTable)
        if table.row_count == 0:
            self._log(
                "[#c4944a]No remote files yet.[/] Refresh after the other computer shares a file."
            )
            return

        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            row_data = table.get_row(row_key)
            filename = row_data[0]
        except Exception:
            self._log("[#c4944a]Select a file[/] in the remote table first.")
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
        self, peer: dict, filename: str, filesize: int | None = None
    ) -> None:
        self.app.call_from_thread(
            self._log,
            f"Downloading [bold]{markup_escape(filename)}[/] from [#5dba6e]{markup_escape(peer['hostname'])}[/]...",
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

        def progress_callback(current: int, total: int) -> None:
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
                f"[#5dba6e]Downloaded[/] {filename} "
                f"({format_size(received)}) -> [#7090a0]{dest}[/]",
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
                f"[#c26068]Download failed:[/] {e}",
            )
            self.app.call_from_thread(
                self.show_notification,
                f"Download failed: {e}",
                "error",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-upload":
            self.action_upload_file()
        elif btn_id == "btn-download":
            self.action_download_file()
        elif btn_id == "btn-refresh":
            self.action_refresh_files()

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
            result = self._parse_target(tokens[1])
            if result:
                host, port = result
                self._cmd_list(host, port)
        elif cmd == "download" and len(tokens) >= 3:
            result = self._parse_target(tokens[1])
            if result:
                host, port = result
                self._do_download_async(
                    {"ip": host, "tcp_port": port, "hostname": host}, tokens[2]
                )
        elif cmd == "upload" and len(tokens) >= 3:
            result = self._parse_target(tokens[1])
            if result:
                host, port = result
                self._do_upload_async(
                    {"ip": host, "tcp_port": port, "hostname": host}, tokens[2]
                )
        elif cmd in ("quit", "exit"):
            self.action_quit_app()
        else:
            self._log(f"[#c4944a]Unknown command:[/] {raw}  (press F1 for help)")

    def _parse_target(self, target: str) -> tuple[str, int] | None:
        if ":" in target:
            host, port_str = target.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                self._log(
                    f"[#c26068]Error:[/] Invalid port '{port_str}' — must be an integer."
                )
                return None
            if not (1 <= port <= 65535):
                self._log(f"[#c26068]Error:[/] Invalid port '{port}'.")
                return None
            return host, port
        return target, self.tcp_port

    def _cmd_peers(self) -> None:
        peers = self.discovery.get_peers()
        if not peers:
            self._log("No peers discovered yet.")
        else:
            for p in peers:
                self._log(
                    f"  [#5dba6e]●[/] [bold #5dba6e]{markup_escape(p['hostname'])}[/]  "
                    f"[#7090a0]{markup_escape(p['ip'])}:{p['tcp_port']}[/]"
                )

    @work(thread=True)
    def _cmd_list(self, host: str, port: int) -> None:
        try:
            files = fetch_file_list(host, port)
            if not files:
                self.app.call_from_thread(
                    self._log, f"No files on [#7090a0]{host}:{port}[/]"
                )
            else:
                for f in files:
                    self.app.call_from_thread(
                        self._log,
                        f"  {markup_escape(f['name'])}  [#7090a0]{format_size(f['size'])}[/]",
                    )
        except Exception as e:
            self.app.call_from_thread(
                self._log,
                f"[#c26068]Error:[/] {e}",
            )


def run_tui(discovery: PeerDiscovery, file_server: FileServer, tcp_port: int) -> None:
    app = LanternApp(discovery, file_server, tcp_port)
    app.run()
