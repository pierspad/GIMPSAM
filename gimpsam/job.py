from __future__ import annotations

from .util import clean_output_line
from typing import Optional
import os
import queue
import subprocess
import threading
import urllib.request

# ---------------------------------------------------------------------------
# Job — background work + logging, shared by every long-running action
# (installs, downloads, removals). Nothing gimpsam does needs root, so this
# is the plain, pty-free variant; any object with the same log/run_cmd/
# run_cmd_capture/download surface (e.g. LazyGimp's richer Job) works as a
# drop-in wherever a Job is expected — every function in this package only
# duck-types it.
# ---------------------------------------------------------------------------

class Job:
    def __init__(self, log_queue: Optional["queue.Queue[str]"] = None):
        self.log_queue = log_queue
        self.cancel_event = threading.Event()
        self.proc: Optional[subprocess.Popen] = None

    def cancel(self):
        self.cancel_event.set()
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def log(self, msg: str):
        print(msg, flush=True)
        if self.log_queue is not None:
            self.log_queue.put(msg)

    def run_cmd(self, cmd: list[str], *, log_as: Optional[list[str]] = None, **kw) -> int:
        # log_as lets a call site substitute a short, redacted description
        # for the echoed command line — needed for anything built with
        # `-c <inline script>`, where the real argv can run to several KB
        # and, worse, may contain secrets (e.g. an HF token interpolated
        # into the script text) that must never hit stdout/the GUI log.
        rc, _ = self.run_cmd_capture(cmd, log_as=log_as, _collect=False, **kw)
        return rc

    def run_cmd_capture(self, cmd: list[str], *, log_as: Optional[list[str]] = None,
                        _collect: bool = True, **kw) -> tuple[int, list[str]]:
        display = log_as if log_as is not None else cmd
        if self.cancel_event.is_set():
            self.log("Cancelled — skipping: " + " ".join(display))
            return -1, []
        self.log("$ " + " ".join(display))
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1, **kw)
        lines: list[str] = []
        for line in iter(self.proc.stdout.readline, ""):
            if line:
                clean = clean_output_line(line.rstrip("\n"))
                if clean:
                    self.log(clean)
                    if _collect:
                        lines.append(clean)
        self.proc.wait()
        rc = self.proc.returncode
        self.proc = None
        return rc, lines

    def download(self, url: str, dest: str, cancel_event: Optional[threading.Event] = None,
                 progress_cb=None, headers: Optional[dict] = None) -> bool:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        part = dest + ".part"
        self.log(f"Downloading {url}")
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as resp, open(part, "wb") as out:
                total = int(resp.headers.get("Content-Length", 0))
                read = 0
                last_pct = -1
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        self.log("Cancelled.")
                        return False
                    buf = resp.read(1024 * 256)
                    if not buf:
                        break
                    out.write(buf)
                    read += len(buf)
                    if progress_cb:
                        progress_cb(read, total)
                    if total:
                        pct = int(read * 100 / total)
                        if pct != last_pct and pct % 5 == 0:
                            self.log(f"  {pct}%  ({read // (1024*1024)} MB / {total // (1024*1024)} MB)")
                            last_pct = pct
            os.replace(part, dest)
            self.log(f"Saved to {dest}")
            return True
        except Exception as e:
            self.log(f"ERROR downloading {url}: {e}")
            return False
        finally:
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass
