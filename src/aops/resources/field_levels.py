"""Which fields Simple mode shows.

Eighty-six settings is the right number for a tool that has to get an
industrial position strip physically correct, and the wrong number to put in
front of someone making their first one. Simple mode hides the ones whose
default is right for nearly everybody; Advanced shows all of them.

THE PROPERTY THAT MATTERS: SIMPLE MODE MUST BE CLOSED
-----------------------------------------------------
Every validation error a Simple-mode user can cause, they must be able to clear
without switching to Advanced. A mode that lets you break the geometry and then
hides the field that would fix it is not a simplification, it is a trap - and a
worse one than the full panel, because the way out is invisible.

So membership here is not just "is this field important". It is closed under the
validation rules: if a Simple field can push the configuration into an error,
whatever clears that error is Simple too. `tests/ui/test_modes.py` walks the
ERROR-severity rules and asserts it.

"Advanced" therefore does not mean unimportant. The quiet zone is critical to
whether the strip reads at all - but it follows from the code size, the tool
derives it correctly, and a first-time user should never have to know the term.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Final


class UiLevel(IntEnum):
    """How much of the configuration a field belongs to."""

    SIMPLE = 0
    ADVANCED = 1

    @property
    def display_name(self) -> str:
        return {UiLevel.SIMPLE: "Simple", UiLevel.ADVANCED: "Advanced"}[self]

    @property
    def description(self) -> str:
        return {
            UiLevel.SIMPLE: (
                "The settings a typical strip needs. Everything hidden keeps a "
                "sensible default, and anything you can break here you can also "
                "fix here."
            ),
            UiLevel.ADVANCED: (
                "Every setting, grouped as before. Needed for unusual media, "
                "print calibration, reader optics and traceability detail."
            ),
        }[self]


#: Fields Simple mode shows: the facts about the job that only the human
#: knows. Everything not listed is Advanced.
#:
#: The geometry fields - pitch, code size, quiet zone, strip height - are
#: deliberately NOT here, and that is the solver's doing: they are consequences
#: of the job, not questions. A Simple-mode user states the machine's speed,
#: the bracket's distance and the devices in use, and presses Design; the
#: geometry appears with a reason attached to every value, and lives in
#: Advanced for the day someone disagrees with a decision.
SIMPLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        # -- the machine ---------------------------------------------------
        "scanner.axis_speed_mm_per_s",
        # -- the installation ----------------------------------------------
        "scanner.mount_distance_mm",
        "scanner.min_codes_in_view",
        # -- the devices (normally filled by a Presets pick) ---------------
        "printer.dpi",
        # -- what it is printed on -----------------------------------------
        "paper.preset",
        "media.media",
        # -- how it leaves the building ------------------------------------
        "output.tiled_pages",
        "output.continuous",
        "printing.scale_percent",
    }
)


#: Fields the job bar carries outside the accordion, visible in both modes.
#:
#: Kept here rather than only in the widget because the closure property is
#: about what a Simple-mode user can *reach*, not about which container it sits
#: in. A field on the job bar is as reachable as one in the Simple set.
#: `position.end_index` is here because the axis-travel box owns it: editing
#: the travel writes the index range, so a finding pointing at the range has a
#: permanently visible control.
JOB_BAR_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "project.machine",
        "project.strip_id",
        "position.end_index",
    }
)

#: Everything a Simple-mode user can see and edit, wherever it lives.
REACHABLE_IN_SIMPLE: Final[frozenset[str]] = SIMPLE_FIELDS | JOB_BAR_FIELDS


def level_for(path: str) -> UiLevel:
    """Which mode a field belongs to."""
    return UiLevel.SIMPLE if path in SIMPLE_FIELDS else UiLevel.ADVANCED


def visible_at(path: str, mode: UiLevel) -> bool:
    """True when a field should be shown in `mode`.

    Answers the question for accordion rows. Job-bar fields are always on show,
    so `always_reachable` is what a caller deciding whether to switch modes
    should ask instead.
    """
    return mode is UiLevel.ADVANCED or path in SIMPLE_FIELDS


def always_reachable(path: str) -> bool:
    """True when a field is on screen regardless of mode."""
    return path in JOB_BAR_FIELDS
