# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at https://mozilla.org/MPL/2.0/.
"""Minimal framed Marionette transport for isolated desktop UI checks."""
import json
import os
import socket


class Marionette:
    """Connects to the explicitly configured local test-control port."""

    def __init__(self):
        self.socket = socket.create_connection(
            ('127.0.0.1', int(os.environ['OB_PORT'])), timeout=20)
        self.sequence = 0
        try:
            self.receive()
            self.call('WebDriver:NewSession', {'capabilities': {'alwaysMatch': {}}})
            self.call('Marionette:SetContext', {'value': 'chrome'})
        except Exception:
            self.socket.close()
            raise

    def read_exactly(self, size):
        """Reads one complete frame or raises when the peer disconnects."""
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.socket.recv(size-len(chunks))
            if not chunk:
                raise ConnectionError('Marionette disconnected')
            chunks.extend(chunk)
        return bytes(chunks)

    def receive(self):
        """Decodes a length-prefixed Marionette JSON message."""
        length = bytearray()
        while (byte := self.read_exactly(1)) != b':':
            length.extend(byte)
        return json.loads(self.read_exactly(int(length)))

    def call(self, name, parameters):
        """Sends a command and raises for a remote WebDriver error."""
        self.sequence += 1
        payload = json.dumps([0, self.sequence, name, parameters]).encode()
        self.socket.sendall(str(len(payload)).encode()+b':'+payload)
        response = self.receive()
        if response[2]:
            raise RuntimeError(response[2])
        return response[3]

    def js(self, source):
        """Evaluates trusted test code in the isolated profile's chrome window."""
        return self.call('WebDriver:ExecuteScript', {'script': source, 'args': []})

    def close(self):
        """Ends the control session and closes its socket."""
        try:
            self.call('WebDriver:DeleteSession', {})
        finally:
            self.socket.close()
