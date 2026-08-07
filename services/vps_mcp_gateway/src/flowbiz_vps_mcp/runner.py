"""Bounded subprocess execution without a shell."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .security import Redactor


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool


class _BoundedCapture:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.data = bytearray()
        self.truncated = False
        self.error: str | None = None

    def drain(self, stream: BinaryIO) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                remaining = self.limit - len(self.data)
                if remaining > 0:
                    self.data.extend(chunk[:remaining])
                if len(chunk) > max(remaining, 0):
                    self.truncated = True
        except (OSError, ValueError) as exc:
            self.error = str(exc)
        finally:
            with suppress(OSError):
                stream.close()

    def text(self) -> str:
        text = bytes(self.data).decode("utf-8", errors="replace")
        if self.truncated:
            text += "\n[OUTPUT TRUNCATED]"
        if self.error:
            text += f"\n[OUTPUT CAPTURE ERROR: {self.error}]"
        return text


class CommandRunner:
    def __init__(self, *, max_output_bytes: int, redactor: Redactor) -> None:
        self.max_output_bytes = max_output_bytes
        self.redactor = redactor

    def run(
        self,
        argv: list[str],
        *,
        timeout_seconds: int,
        working_directory: Path | None = None,
    ) -> CommandResult:
        self._validate_argv(argv)
        started = time.monotonic()
        env = {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "HOME": "/nonexistent",
        }

        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(working_directory) if working_directory else None,
                env=env,
                shell=False,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            duration_ms = round((time.monotonic() - started) * 1000)
            return CommandResult(
                argv=list(argv),
                exit_code=126,
                stdout="",
                stderr=self.redactor.redact(f"Failed to start command: {exc}"),
                duration_ms=duration_ms,
                timed_out=False,
                stdout_truncated=False,
                stderr_truncated=False,
            )

        assert process.stdout is not None
        assert process.stderr is not None
        stdout_capture = _BoundedCapture(self.max_output_bytes)
        stderr_capture = _BoundedCapture(self.max_output_bytes)
        stdout_thread = threading.Thread(
            target=stdout_capture.drain,
            args=(process.stdout,),
            name="flowbiz-vps-mcp-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=stderr_capture.drain,
            args=(process.stderr,),
            name="flowbiz-vps-mcp-stderr",
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        timed_out = False
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_process_group(process.pid)
            exit_code = process.wait(timeout=5)

        # A command may exit while a child keeps inherited output pipes open. Do
        # not let that hold the executor indefinitely or leave an orphan process.
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            self._kill_process_group(process.pid)
            with suppress(OSError):
                process.stdout.close()
            with suppress(OSError):
                process.stderr.close()
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)

        stdout = stdout_capture.text()
        stderr = stderr_capture.text()
        duration_ms = round((time.monotonic() - started) * 1000)
        if timed_out:
            timeout_message = f"Command exceeded timeout of {timeout_seconds} seconds."
            stderr = f"{stderr}\n{timeout_message}".strip()

        return CommandResult(
            argv=list(argv),
            exit_code=exit_code,
            stdout=self.redactor.redact(stdout),
            stderr=self.redactor.redact(stderr),
            duration_ms=duration_ms,
            timed_out=timed_out,
            stdout_truncated=stdout_capture.truncated,
            stderr_truncated=stderr_capture.truncated,
        )

    @staticmethod
    def _kill_process_group(pid: int) -> None:
        with suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)

    @staticmethod
    def _validate_argv(argv: list[str]) -> None:
        if not argv:
            raise ValueError("argv cannot be empty")
        executable = Path(argv[0])
        if not executable.is_absolute():
            raise ValueError("Executable path must be absolute")
        for token in argv:
            if not isinstance(token, str) or not token or "\x00" in token:
                raise ValueError("argv contains an unsafe token")
