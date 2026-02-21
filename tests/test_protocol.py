"""
Tests for protocol.py — message framing and file transfer helpers.
"""

import io
import socket
import struct
import threading
import tempfile
import os

import pytest

from lantern.protocol import send_msg, recv_msg, send_file, recv_file, _recv_exactly


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_socket_pair():
    """Return a connected (client, server) socket pair."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    server, _ = server_sock.accept()
    server_sock.close()
    return client, server


# ---------------------------------------------------------------------------
# _recv_exactly
# ---------------------------------------------------------------------------


class TestRecvExactly:
    def test_reads_exact_bytes(self):
        client, server = make_socket_pair()
        try:
            client.sendall(b"hello")
            result = _recv_exactly(server, 5)
            assert result == b"hello"
        finally:
            client.close()
            server.close()

    def test_returns_none_on_disconnect(self):
        client, server = make_socket_pair()
        client.close()
        result = _recv_exactly(server, 10)
        assert result is None
        server.close()

    def test_reads_across_multiple_chunks(self):
        """Simulate fragmented delivery by sending bytes one at a time."""
        client, server = make_socket_pair()
        try:
            data = b"fragmented"

            def send_slowly():
                for byte in data:
                    client.sendall(bytes([byte]))

            t = threading.Thread(target=send_slowly)
            t.start()
            result = _recv_exactly(server, len(data))
            t.join()
            assert result == data
        finally:
            client.close()
            server.close()


# ---------------------------------------------------------------------------
# send_msg / recv_msg
# ---------------------------------------------------------------------------


class TestMessageFraming:
    def test_roundtrip_short_message(self):
        client, server = make_socket_pair()
        try:
            send_msg(client, "hello world")
            assert recv_msg(server) == "hello world"
        finally:
            client.close()
            server.close()

    def test_roundtrip_empty_string(self):
        client, server = make_socket_pair()
        try:
            send_msg(client, "")
            assert recv_msg(server) == ""
        finally:
            client.close()
            server.close()

    def test_roundtrip_unicode(self):
        client, server = make_socket_pair()
        try:
            msg = "こんにちは — Lantern 🏮"
            send_msg(client, msg)
            assert recv_msg(server) == msg
        finally:
            client.close()
            server.close()

    def test_multiple_messages_in_sequence(self):
        client, server = make_socket_pair()
        try:
            messages = ["first", "second", "third"]
            for m in messages:
                send_msg(client, m)
            for m in messages:
                assert recv_msg(server) == m
        finally:
            client.close()
            server.close()

    def test_recv_returns_none_on_disconnect(self):
        client, server = make_socket_pair()
        client.close()
        assert recv_msg(server) is None
        server.close()


# ---------------------------------------------------------------------------
# send_file / recv_file
# ---------------------------------------------------------------------------


class TestFileTransfer:
    def test_roundtrip_small_file(self, tmp_path):
        src = tmp_path / "src.bin"
        dst = tmp_path / "dst.bin"
        content = b"binary content 1234"
        src.write_bytes(content)

        client, server = make_socket_pair()
        try:

            def sender():
                send_file(client, str(src))
                client.close()

            t = threading.Thread(target=sender)
            t.start()

            size_msg = recv_msg(server)
            filesize = int(size_msg)
            received = recv_file(server, str(dst), filesize)
            t.join()
        finally:
            server.close()

        assert received == len(content)
        assert dst.read_bytes() == content

    def test_roundtrip_empty_file(self, tmp_path):
        src = tmp_path / "empty.bin"
        dst = tmp_path / "empty_dst.bin"
        src.write_bytes(b"")

        client, server = make_socket_pair()
        try:

            def sender():
                send_file(client, str(src))
                client.close()

            t = threading.Thread(target=sender)
            t.start()

            size_msg = recv_msg(server)
            filesize = int(size_msg)
            received = recv_file(server, str(dst), filesize)
            t.join()
        finally:
            server.close()

        assert received == 0
        assert dst.read_bytes() == b""

    def test_progress_callback_called(self, tmp_path):
        src = tmp_path / "prog.bin"
        dst = tmp_path / "prog_dst.bin"
        content = b"x" * 8192
        src.write_bytes(content)

        calls = []

        def progress(current, total):
            calls.append((current, total))

        client, server = make_socket_pair()
        try:

            def sender():
                send_file(client, str(src))
                client.close()

            t = threading.Thread(target=sender)
            t.start()

            size_msg = recv_msg(server)
            filesize = int(size_msg)
            recv_file(server, str(dst), filesize, progress_callback=progress)
            t.join()
        finally:
            server.close()

        assert len(calls) > 0
        assert calls[-1][0] == len(content)

    def test_cancel_event_stops_transfer(self, tmp_path):
        src = tmp_path / "big.bin"
        dst = tmp_path / "big_dst.bin"
        content = b"z" * (1024 * 64)  # 64 KB
        src.write_bytes(content)

        cancel = threading.Event()
        cancel.set()  # Cancel immediately

        client, server = make_socket_pair()
        try:

            def sender():
                send_file(client, str(src))
                client.close()

            t = threading.Thread(target=sender)
            t.start()

            size_msg = recv_msg(server)
            filesize = int(size_msg)
            received = recv_file(server, str(dst), filesize, cancel_event=cancel)
            t.join()
        finally:
            server.close()

        # Transfer was cancelled — received should be less than total
        assert received < len(content)
