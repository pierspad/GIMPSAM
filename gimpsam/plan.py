from __future__ import annotations

from .job import Job
from dataclasses import dataclass
from typing import Callable

# ---------------------------------------------------------------------------
# The installer's data model: a plan (checklist) of actions the user has
# queued up, plus the wizard pages used to build one interactively. Neither
# of these two classes touches Tk or the filesystem — they are pure data,
# which is what makes them reusable from the paginated wizard, from Quick
# Setup's one-click prefill, and (if it's ever wanted) from a future CLI
# "plan" subcommand, without duplicating any install/remove logic.
# ---------------------------------------------------------------------------

@dataclass
class PlannedAction:
    """One row of the checklist: something to do later, not now.

    `key` is what makes the checklist idempotent — toggling the same button
    twice adds then removes the same entry instead of piling up duplicates.
    `run` is only ever invoked by the shared executor (see
    LazyGimpApp._run_plan), never at the moment the user clicks a button.
    """
    key: str
    label: str
    kind: str  # "install" | "remove" — cosmetic only (icon/colour on Review)
    run: Callable[["Job"], None]


class InstallPlan:
    """An ordered, de-duplicated checklist of PlannedAction. A dict keyed by
    `action.key` gives both O(1) membership checks and stable insertion
    order (Python dicts preserve it), which is exactly what the Review page
    and the executor need."""

    def __init__(self):
        self._items: dict[str, PlannedAction] = {}

    def add(self, action: PlannedAction) -> None:
        self._items[action.key] = action

    def toggle(self, action: PlannedAction) -> bool:
        """Add `action` if its key isn't queued yet, else remove it.
        Returns the new membership (True = now queued)."""
        if action.key in self._items:
            del self._items[action.key]
            return False
        self._items[action.key] = action
        return True

    def discard(self, key: str) -> None:
        self._items.pop(key, None)

    def has(self, key: str) -> bool:
        return key in self._items

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items.values())


@dataclass
class WizardStep:
    """One page of the paginated installer. `prerequisite=True` marks the
    one step (GIMP itself) that is skipped entirely when already satisfied,
    and that cannot be skipped manually while it's showing."""
    key: str
    title: str
    prerequisite: bool = False


