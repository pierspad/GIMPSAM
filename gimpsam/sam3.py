from __future__ import annotations

from .backend import backend_ready
from .constants import SAM3_HF_PAGE, SAM3_HF_REPO_ID, VENV_PYTHON
from .models import MODEL_BY_KEY, model_path
from typing import Optional
import os
import shutil

# ---------------------------------------------------------------------------
# SAM 3.1 — gated on Hugging Face. The generic huggingface_hub error text
# ("...we cannot find the requested files in the local cache...") is what
# you get for a plain 401/403 too, so string-sniffing the exception message
# alone cannot reliably tell "not approved yet" apart from "bad token" apart
# from "actually offline". Instead, probe explicitly and in order: does the
# token authenticate at all (whoami), does IT have access to the gated repo
# (model_info) — only THEN attempt the real (multi-GB) download. This is
# what actually fixes "non so perché non scarica il modello sam3.1": the
# failure now names the exact cause instead of a generic cache-miss message.
# ---------------------------------------------------------------------------

def build_sam3_download_script(dest: str, token: str) -> str:
    return (
        "import sys\n"
        "from huggingface_hub import HfApi, snapshot_download\n"
        "try:\n"
        "    from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError\n"
        "except ImportError:\n"
        "    GatedRepoError = RepositoryNotFoundError = Exception\n"
        f"token = {token!r} or None\n"
        "api = HfApi()\n"
        "try:\n"
        "    api.whoami(token=token)\n"
        "except Exception as e:\n"
        "    print('ERROR-AUTH: token was rejected — ' + str(e).splitlines()[0])\n"
        "    sys.exit(1)\n"
        "try:\n"
        f"    api.model_info({SAM3_HF_REPO_ID!r}, token=token)\n"
        "except GatedRepoError:\n"
        "    print('ERROR-GATED: access to " + SAM3_HF_REPO_ID + " has not been approved yet for this account')\n"
        "    sys.exit(1)\n"
        "except RepositoryNotFoundError:\n"
        "    print('ERROR-AUTH: this token has no access to " + SAM3_HF_REPO_ID + " (401)')\n"
        "    sys.exit(1)\n"
        "except Exception as e:\n"
        "    print('ERROR-NETWORK: ' + str(e).splitlines()[0])\n"
        "    sys.exit(1)\n"
        "try:\n"
        f"    snapshot_download(repo_id={SAM3_HF_REPO_ID!r}, local_dir={dest!r}, token=token)\n"
        f"    print('SAM 3.1 checkpoint downloaded to', {dest!r})\n"
        "except Exception as e:\n"
        "    print('ERROR-OTHER: ' + str(e).splitlines()[0])\n"
        "    sys.exit(1)\n"
    )


def classify_sam3_failure(lines: list[str]) -> Optional[str]:
    for line in reversed(lines):
        if line.startswith("ERROR-"):
            return line
    return None


SAM3_FAILURE_MESSAGES = {
    "ERROR-GATED": (
        "Access denied — your Hugging Face account has requested but not yet been approved for {repo}. "
        "Request access at {page} if you haven't, wait for the approval email, then try again with the same token."
    ),
    "ERROR-AUTH": (
        "The token was rejected or has no access to {repo}. Generate a fresh READ token at "
        "huggingface.co/settings/tokens (after being approved at {page}) and paste it in again."
    ),
    "ERROR-NETWORK": (
        "Couldn't reach Hugging Face — check your internet connection (and any proxy/firewall), then retry. "
        "This is a several-GB download, so a flaky connection is a common cause."
    ),
}


def sam3_failure_message(tag: Optional[str]) -> str:
    if tag is None:
        return "Couldn't download the SAM 3.1 checkpoint — see the log above for the exact error."
    kind = tag.split(":", 1)[0].strip()
    detail = tag.split(":", 1)[1].strip() if ":" in tag else ""
    template = SAM3_FAILURE_MESSAGES.get(kind)
    if template is None:
        return f"Couldn't download the SAM 3.1 checkpoint: {detail or tag}"
    base = template.format(repo=SAM3_HF_REPO_ID, page=SAM3_HF_PAGE)
    return f"{base}\n\nDetails: {detail}" if detail else base


def download_sam3(job, token: str) -> tuple[bool, Optional[str]]:
    if not backend_ready():
        job.log("Set up the Python backend first.")
        return False, None
    dest = model_path(MODEL_BY_KEY["sam3"])
    os.makedirs(dest, exist_ok=True)
    script = build_sam3_download_script(dest, token)
    job.log(f"Checking Hugging Face access for {SAM3_HF_REPO_ID}...")
    # NEVER echo `script` itself: it has the HF token interpolated into its
    # source (see build_sam3_download_script) and, being several KB long, a
    # raw dump also lands the script's own `print('ERROR-...')` lines in the
    # log right after the "Checking..." message — easy to misread as a real
    # failure even when the download goes on to succeed. `log_as` swaps in
    # a short, secret-free description for display purposes only; the real
    # `cmd` (with the real token) still runs unchanged.
    rc, lines = job.run_cmd_capture(
        [VENV_PYTHON, "-c", script],
        log_as=[VENV_PYTHON, "-c", f"<verify token, then download {SAM3_HF_REPO_ID} to {dest}>"],
    )
    ok = rc == 0
    tag = classify_sam3_failure(lines)
    if ok:
        job.log("SAM 3.1 checkpoint ready.")
    # On failure, leave the message to the caller: both the wizard and the
    # CLI already follow up with sam3_failure_message(tag), which names the
    # actual cause (bad token / not yet approved / offline) — a bare
    # "Download failed." here would only precede that with a useless line.
    return ok, tag


def remove_sam3(job) -> bool:
    dest = model_path(MODEL_BY_KEY["sam3"])
    if os.path.isdir(dest):
        shutil.rmtree(dest)
        job.log(f"Removed {dest}")
    else:
        job.log("SAM 3.1 was not installed.")
    return True
