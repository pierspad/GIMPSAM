#!/usr/bin/env python3
"""Thin launcher for a source checkout — the real code lives in gimpsam/.

Run `python3 installer.py` (equivalent: `python3 -m gimpsam`): no
subcommand opens the GUI; every action is also a plain CLI command
(`python3 installer.py --help`).

Run it ephemerally (nothing is left on disk afterwards): pass
--ephemeral, which makes the installer delete itself when it closes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gimpsam.cli import main

if __name__ == "__main__":
    main()
