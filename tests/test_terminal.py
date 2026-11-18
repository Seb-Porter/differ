"""The pseudoterminal on the system the tests run on: what the sessions rely on, checked against a child process that
records what it reads instead of echoing it, since a Windows pseudo console renders what a process prints."""

import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import terminal

# Raw mode, then a line once it is ready, then every byte it reads into the file its first argument names, until it
# reads a q, when it sets a title and exits; a ? prints the terminal's size. It starts a grandchild that sleeps, whose pid it prints, so a test can see
# whether ending the child ends the processes it started.
CHILD = r"""
import os, subprocess, sys
if sys.platform == "win32":
    import ctypes, msvcrt
    ctypes.windll.kernel32.SetConsoleMode(msvcrt.get_osfhandle(0), 0x0200)
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    ctypes.windll.kernel32.SetConsoleCP(65001)
else:
    import tty
    tty.setraw(0)
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
os.write(1, f"ready {grandchild.pid}\r\n".encode())
with open(sys.argv[1], "ab", buffering=0) as log:
    while data := os.read(0, 1024):
        log.write(data)
        if b"?" in data:
            os.write(1, "size {} {}\r\n".format(*os.get_terminal_size(1)).encode())
        if b"q" in data:
            os.write(1, "\x1b]0;✳ done\x07bye\r\n".encode())
            break
"""


def wait_for(condition: Callable[[], bool], timeout: float = 15) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("timed out")


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        try:
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class Child:
    """The child in a pseudoterminal, with what it printed so far, read in a thread until the pseudoterminal ends."""

    def __init__(self, tmp_path: Path) -> None:
        self.log = tmp_path / "read.log"
        self.log.touch()
        script = tmp_path / "child.py"
        script.write_text(CHILD, encoding="utf-8")
        self.term = terminal.spawn([sys.executable, str(script), str(self.log)], tmp_path, dict(os.environ), 80, 24)
        self.output = bytearray()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        wait_for(lambda: b"ready" in self.output)
        self.grandchild = int(bytes(self.output).split(b"ready ")[1].split()[0])

    def _read(self) -> None:
        while data := self.term.read():
            self.output += data

    def type(self, data: bytes) -> None:
        left = memoryview(data)
        while left:
            if written := self.term.write(left):
                left = left[written:]
            else:
                self.term.wait_writable(0.2)


def test_the_process_reads_what_is_typed_byte_for_byte(tmp_path: Path) -> None:
    child = Child(tmp_path)
    typed = b"\x1b[200~first line\nsecond line \xe2\x9c\xb3\x1b[201~" + b"\x1b" + b"x\x03" + b"\r"
    child.type(typed)
    wait_for(lambda: child.log.read_bytes() == typed)
    child.type(b"q")
    assert child.term.proc.wait(timeout=10) == 0
    child.reader.join(10)
    assert not child.reader.is_alive()
    child.term.close()
    _end(child.grandchild)


def test_the_reader_sees_the_title_the_process_sets_and_the_end_of_the_output(tmp_path: Path) -> None:
    child = Child(tmp_path)
    child.type(b"q")
    child.reader.join(10)
    assert not child.reader.is_alive()
    printed = bytes(child.output)
    assert "\x1b]0;✳ done\x07".encode() in printed or "\x1b]2;✳ done\x07".encode() in printed
    assert b"bye" in printed
    child.term.close()
    _end(child.grandchild)


def test_the_stops_end_the_process_and_the_processes_it_started(tmp_path: Path) -> None:
    child = Child(tmp_path)
    assert alive(child.grandchild)
    for stage, wait in terminal.STOPS:
        if child.term.proc.poll() is not None:
            break
        terminal.stop(child.term.proc, stage)
        try:
            child.term.proc.wait(timeout=wait)
        except Exception:  # noqa: BLE001 - the next stage follows
            pass
    assert child.term.proc.poll() is not None
    wait_for(lambda: not alive(child.grandchild), timeout=5)
    child.reader.join(10)
    assert not child.reader.is_alive()
    child.term.close()


def test_a_resize_reaches_the_process(tmp_path: Path) -> None:
    child = Child(tmp_path)
    child.term.resize(100, 30)
    child.type(b"?")
    wait_for(lambda: b"size 100 30" in child.output)
    child.type(b"q")
    assert child.term.proc.wait(timeout=10) == 0
    child.term.close()
    _end(child.grandchild)


def _end(pid: int) -> None:
    if not alive(pid):
        return
    if sys.platform == "win32":
        import subprocess

        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, 9)
