"""GUI smoke test — needs a real display (CI runs it under Xvfb).

Opens the actual app and walks EVERY screen: landing, the SAM setup
page, back to landing — then quits. Any exception raised in a Tk
callback fails the run.

Not named test_* on purpose: `unittest discover` must keep passing on
headless boxes; this file is invoked explicitly as
    xvfb-run -a python tests/gui_smoke.py
"""
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gimpsam.compat import _CTK_OK, _TK_OK, ctk  # noqa: E402

if not _TK_OK:
    print("tkinter is not available — this smoke test needs python3-tk", file=sys.stderr)
    sys.exit(2)
if not _CTK_OK:
    print("customtkinter is not available — pip install customtkinter", file=sys.stderr)
    sys.exit(2)

from gimpsam.gui.app import GimpSamApp  # noqa: E402
from gimpsam.gui.theme import BG  # noqa: E402

failures: list[str] = []
ctk.set_appearance_mode("dark")
root = ctk.CTk(fg_color=BG)


def fail(kind, exc, tb):
    failures.append("".join(traceback.format_exception(kind, exc, tb)))
    root.after(0, root.destroy)


root.report_callback_exception = fail
app = GimpSamApp(root)

STEPS = [
    lambda: app.show_sam_setup(),
    lambda: app.show_landing(),
    lambda: root.destroy(),
]


def run_step(i=0):
    if i >= len(STEPS) or not root.winfo_exists():
        return
    name = getattr(STEPS[i], "__name__", f"step {i}")
    try:
        STEPS[i]()
    except Exception:
        failures.append(f"--- {name} ---\n" + traceback.format_exc())
        root.destroy()
        return
    root.after(250, lambda: run_step(i + 1))


root.after(300, run_step)
root.mainloop()

if failures:
    print("GUI smoke test FAILED:\n" + "\n".join(failures), file=sys.stderr)
    sys.exit(1)
print("GUI smoke test OK — every screen rendered without callback errors.")
