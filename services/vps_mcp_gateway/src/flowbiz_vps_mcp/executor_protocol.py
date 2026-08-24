"""Small bounded JSON protocol over a local Unix domain socket."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

MAX_REQUEST_BYTES = 65536
# Two independently bounded output streams may each be up to 1 MiB.
MAX_RESPONSE_BYTES = 2_200_000
PROTOCOL_VERSION = 1


def send_executor_request(
    socket_path: Path,
    payload: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    message = json.dumps(
        {"version": PROTOCOL_VERSION, **payload},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    if len(message) > MAX_REQUEST_BYTES:
        raise ValueError("Executor request exceeds maximum size")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall(message)
        response = _read_line(client, MAX_RESPONSE_BYTES)
    decoded = json.loads(response.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError("Executor returned a non-object response")
    return decoded


def _read_line(connection: socket.socket, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = connection.recv(min(4096, max_bytes + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > max_bytes:
            raise ValueError("Executor message exceeds maximum size")
        if b"\n" in chunk:
            break
    data = b"".join(chunks)
    return data.split(b"\n", 1)[0]
