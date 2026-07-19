from __future__ import annotations

from . import __version__
from .backend import (backend_ready, install_sam_backend, install_sam3_transformers,
                      remove_sam_backend, venv_exists, write_sam_info)
from .constants import TORCH_INDEX_URLS
from .hardware import detect_hardware, recommended_model_key, recommended_torch_index
from .job import Job
from .models import MODEL_BY_KEY, MODEL_REGISTRY, model_installed, model_path
from .plugin import install_plugin, plugin_installed, remove_plugin, write_plugin_settings
from .sam3 import download_sam3, remove_sam3, sam3_failure_message
from .util import _self_destruct_if_ephemeral
import argparse
import os
import shutil
import sys

# ---------------------------------------------------------------------------
# Headless CLI — every operation the Tk wizard can do, scriptable. This is
# also the surface LazyGimp drives when it delegates SAM setup, so keep it
# stable: flags are an API here.
# ---------------------------------------------------------------------------

def _resolve_torch_index(args) -> str:
    if args.torch_index:
        return args.torch_index
    return recommended_torch_index(detect_hardware())


def cmd_status(_args) -> int:
    print(f"gimpsam             : {__version__}")
    print(f"SAM plug-in         : {'installed' if plugin_installed() else 'not installed'}")
    print(f"SAM Python backend  : {'ready' if backend_ready() else ('venv exists but broken' if venv_exists() else 'not installed')}")
    installed = [m.key for m in MODEL_REGISTRY if model_installed(m)]
    print(f"SAM models          : {', '.join(installed) if installed else '(none)'}")
    return 0


def cmd_install(args) -> int:
    job = Job()
    ok = install_plugin(job, ref=args.ref)
    ok &= install_sam_backend(job, _resolve_torch_index(args))
    if ok and not any(model_installed(m) for m in MODEL_REGISTRY):
        rec = MODEL_BY_KEY[recommended_model_key(detect_hardware())]
        if job.download(rec.url, model_path(rec), job.cancel_event):
            write_plugin_settings(rec)
            write_sam_info([rec.key])
    return 0 if ok else 1


def cmd_remove(_args) -> int:
    job = Job()
    remove_plugin(job)
    remove_sam_backend(job)
    return 0


def cmd_plugin_install(args) -> int:
    return 0 if install_plugin(Job(), ref=args.ref) else 1


def cmd_plugin_remove(_args) -> int:
    return 0 if remove_plugin(Job()) else 1


def cmd_backend_install(args) -> int:
    return 0 if install_sam_backend(Job(), _resolve_torch_index(args)) else 1


def cmd_backend_remove(_args) -> int:
    return 0 if remove_sam_backend(Job()) else 1


def cmd_model_list(_args) -> int:
    rec = recommended_model_key(detect_hardware())
    print(f"Recommended for this hardware: {rec}\n")
    for m in MODEL_REGISTRY:
        mark = "*" if m.key == rec else " "
        state = "installed" if model_installed(m) else "-"
        print(f" {mark} {m.key:22s} {m.family:5s} {m.size:8s} quality={m.quality} speed={m.speed}  [{state}]")
    return 0


def cmd_model_install(args) -> int:
    job = Job()
    ok = True
    for key in args.keys:
        spec = MODEL_BY_KEY.get(key)
        if not spec:
            print(f"unknown SAM model: {key}", file=sys.stderr)
            ok = False
            continue
        if model_installed(spec):
            print(f"{key} already installed")
            continue
        if spec.family == "SAM3":
            print("Use 'sam3 download --token ...' for SAM 3.1 (it's gated).", file=sys.stderr)
            ok = False
            continue
        if job.download(spec.url, model_path(spec), job.cancel_event):
            write_plugin_settings(spec)
            write_sam_info([spec.key])
        else:
            ok = False
    return 0 if ok else 1


def cmd_model_remove(args) -> int:
    job = Job()
    for key in args.keys:
        spec = MODEL_BY_KEY.get(key)
        if not spec:
            print(f"unknown SAM model: {key}", file=sys.stderr)
            continue
        dest = model_path(spec)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
            job.log(f"Removed {dest}")
        elif os.path.isfile(dest):
            os.remove(dest)
            job.log(f"Removed {dest}")
        else:
            job.log(f"{key} was not installed")
    return 0


def cmd_sam3_download(args) -> int:
    job = Job()
    ok, tag = download_sam3(job, args.token)
    if not ok:
        print(sam3_failure_message(tag), file=sys.stderr)
    return 0 if ok else 1


def cmd_sam3_remove(_args) -> int:
    remove_sam3(Job())
    return 0


def cmd_sam3_transformers(_args) -> int:
    return 0 if install_sam3_transformers(Job()) else 1


def _add_torch_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--torch-index", default=None, metavar="URL",
                   help="PyTorch wheel index URL (default: auto-detected from your GPU); "
                        f"known indexes: {', '.join(TORCH_INDEX_URLS.values())}")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gimpsam",
        description="Segment Anything for GIMP — plug-in, Python backend, and SAM models. "
                     "No subcommand opens the GUI; every action is also a plain CLI command.",
    )
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--ephemeral", action="store_true", help="self-delete this file when the GUI closes")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("status", help="show what's installed").set_defaults(func=cmd_status)

    p_install = sub.add_parser("install", help="plug-in + backend + recommended model, in one go")
    p_install.add_argument("--ref", default=None, help="git ref to take the plug-in files from "
                                                        "(default: this release's own tag)")
    _add_torch_flags(p_install)
    p_install.set_defaults(func=cmd_install)

    sub.add_parser("remove", help="remove the plug-in, the backend, and every model") \
       .set_defaults(func=cmd_remove)

    p_plugin = sub.add_parser("plugin", help="just the GIMP plug-in files")
    plugin_sub = p_plugin.add_subparsers(dest="plugin_command", required=True)
    p_pi = plugin_sub.add_parser("install", help="install/refresh the plug-in files")
    p_pi.add_argument("--ref", default=None, help="git ref to take the plug-in files from")
    p_pi.set_defaults(func=cmd_plugin_install)
    plugin_sub.add_parser("remove", help="remove the plug-in files").set_defaults(func=cmd_plugin_remove)

    p_backend = sub.add_parser("backend", help="just the Python backend (venv + PyTorch + SAM)")
    backend_sub = p_backend.add_subparsers(dest="backend_command", required=True)
    p_bi = backend_sub.add_parser("install", help="create the venv and install PyTorch + SAM")
    _add_torch_flags(p_bi)
    p_bi.set_defaults(func=cmd_backend_install)
    backend_sub.add_parser("remove", help="delete the venv, models and all").set_defaults(func=cmd_backend_remove)

    p_model = sub.add_parser("model", help="manage individual SAM models")
    model_sub = p_model.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("list", help="list every SAM model and its install state").set_defaults(func=cmd_model_list)
    p_mi = model_sub.add_parser("install", help="download one or more SAM models")
    p_mi.add_argument("keys", nargs="+")
    p_mi.set_defaults(func=cmd_model_install)
    p_mr = model_sub.add_parser("remove", help="delete one or more SAM models")
    p_mr.add_argument("keys", nargs="+")
    p_mr.set_defaults(func=cmd_model_remove)

    p_sam3 = sub.add_parser("sam3", help="SAM 3.1 (gated on Hugging Face)")
    sam3_sub = p_sam3.add_subparsers(dest="sam3_command", required=True)
    p_s3d = sam3_sub.add_parser("download", help="check access and download the SAM 3.1 checkpoint")
    p_s3d.add_argument("--token", required=True, help="Hugging Face read token")
    p_s3d.set_defaults(func=cmd_sam3_download)
    sam3_sub.add_parser("remove", help="delete the SAM 3.1 checkpoint").set_defaults(func=cmd_sam3_remove)
    sam3_sub.add_parser("transformers", help="install/upgrade transformers (needed to run SAM 3.1)") \
            .set_defaults(func=cmd_sam3_transformers)

    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    if getattr(args, "command", None) is None:
        from .gui import launch_gui
        launch_gui()
        return
    rc = args.func(args)
    _self_destruct_if_ephemeral()
    sys.exit(rc)
