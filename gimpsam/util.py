from __future__ import annotations

import re


def clean_output_line(line: str) -> str:
    """Strip ANSI escape sequences (colors, cursor movements) and resolve
    carriage returns (keeping only the final overwritten text)."""
    ansi_escape = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    line = ansi_escape.sub('', line)
    if '\r' in line:
        parts = line.split('\r')
        non_empty = [p for p in parts if p.strip()]
        line = non_empty[-1] if non_empty else parts[-1]
    return line
