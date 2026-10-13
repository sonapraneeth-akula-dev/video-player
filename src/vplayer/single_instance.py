"""Per-user primary election and local forwarding of external opens."""

import ctypes
import getpass
import json
import logging
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger("vplayer")
MAX_REQUEST = 65536


def instance_name():
    return f"vplayer-{getpass.getuser()}"


def open_message(items, *, new_window=False):
    paths = [item if item.lower().startswith("sftp://") else os.path.abspath(item) for item in items]
    payload = json.dumps({"v": 1, "new_window": new_window, "items": paths}).encode("utf-8")
    if len(payload) > MAX_REQUEST:
        raise ValueError("Too many files to forward in one request (64 KB limit)")
    return payload


class SingleInstance:
    def __init__(self, receiver, name=None):
        self.receiver = receiver
        self.name = name or instance_name()
        temp = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation))
        self.lock = QLockFile(str(temp / f"{self.name}.lock"))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer()
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._buffers = {}

    def start(self, payload):
        deadline = time.monotonic() + 3
        while True:
            if self.lock.tryLock(0):
                QLocalServer.removeServer(self.name)
                if not self.server.listen(self.name):
                    self.lock.unlock()
                    raise RuntimeError(f"Cannot start local server: {self.server.errorString()}")
                self.server.newConnection.connect(self._accept)
                return True
            if self.lock.error() != QLockFile.LockError.LockFailedError:
                raise RuntimeError(f"Cannot acquire instance lock: {self.lock.error().name}")
            client = QLocalSocket()
            client.connectToServer(self.name)
            remaining = max(1, int((deadline - time.monotonic()) * 1000))
            if client.waitForConnected(min(200, remaining)):
                if sys.platform == "win32":
                    ctypes.WinDLL("user32", use_last_error=True).AllowSetForegroundWindow(0xFFFFFFFF)
                message = payload + b"\n"
                if client.write(message) != len(message):
                    raise RuntimeError(f"Could not forward open request: {client.errorString()}")
                if client.bytesToWrite() and not client.waitForBytesWritten(remaining):
                    raise RuntimeError(f"Could not forward open request: {client.errorString()}")
                if not client.waitForReadyRead(max(1, int((deadline - time.monotonic()) * 1000))):
                    raise RuntimeError("Running player did not acknowledge the open request")
                if bytes(client.readAll()) != b"ok\n":
                    raise RuntimeError("Running player did not accept the open request")
                client.disconnectFromServer()
                return False
            client.abort()
            if time.monotonic() >= deadline:
                raise RuntimeError("Running player did not start its local server within 3 seconds")
            time.sleep(0.05)

    def _accept(self):
        while self.server.hasPendingConnections():
            client = self.server.nextPendingConnection()
            self._buffers[client] = bytearray()
            client.readyRead.connect(lambda client=client: self._read(client))
            client.disconnected.connect(lambda client=client: self._done(client))
            timer = QTimer(client)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda client=client: client.abort())
            timer.start(3000)

    def _read(self, client):
        buffer = self._buffers[client]
        buffer.extend(bytes(client.read(MAX_REQUEST + 2 - len(buffer))))
        if len(buffer) > MAX_REQUEST + 1 or client.bytesAvailable() or buffer.count(b"\n") > 1:
            log.warning("Ignoring oversized or multiple IPC messages")
            client.write(b"error\n")
            client.flush()
            client.disconnectFromServer()
            return
        if buffer.endswith(b"\n"):
            accepted = self.receiver.receive_open_request(bytes(buffer[:-1]))
            client.write(b"ok\n" if accepted else b"error\n")
            client.flush()
            client.disconnectFromServer()

    def _done(self, client):
        if client in self._buffers and self._buffers[client] and not self._buffers[client].endswith(b"\n"):
            log.warning("Ignoring incomplete IPC request")
        self._buffers.pop(client, None)
        client.deleteLater()

    def close(self):
        if self.lock.isLocked():
            self.server.close()
            QLocalServer.removeServer(self.name)
            self.lock.unlock()
