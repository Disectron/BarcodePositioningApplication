"""Exception types for the pure domain layer."""

from __future__ import annotations


class AopsError(Exception):
    """Base class for all AOPS domain errors."""


class GeometryError(AopsError):
    """Raised when a geometry is physically impossible to lay out.

    In the GUI the user should never see this: validation rule PAG-001 fires
    first and disables export. It remains the last line of defence for the CLI
    and for tests, and it must never be swallowed - silently splitting a cell
    would ship a strip with a symbol cut in half.
    """


class ProjectFileError(AopsError):
    """Raised when a `.aops` file cannot be read or is from a future schema."""


class SymbologyNotImplemented(AopsError):
    """Raised when an unimplemented symbology is asked to encode.

    Deliberately fatal rather than falling back to another symbology: a strip
    silently printed in the wrong symbology is worse than no strip at all.
    """

    def __init__(self, symbology: str, reason: str) -> None:
        super().__init__(f"{symbology} is not implemented: {reason}")
        self.symbology = symbology
        self.reason = reason


class SymbolExtractionError(AopsError):
    """Raised when a module matrix cannot be recovered from an encoder bitmap."""


class EncoderUnavailable(AopsError):
    """Raised when a symbology's backend library is missing or broken."""
