"""Validation report types and the rule-engine entry point.

Findings carry a dotted field path so the UI can put a coloured border on the
exact spin box that caused them, and a `hint` giving the corrective action.
Telling an engineer "invalid geometry" wastes their time; telling them
"symbol 12.000 mm exceeds pitch 10.000 mm - reduce the symbol or raise the
pitch" does not.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

from aops.core.config import AopsConfig
from aops.core.enums import Severity

if TYPE_CHECKING:
    from aops.core.stats import DerivedGeometry


@dataclass(frozen=True, slots=True)
class Fix:
    """A concrete correction the user can apply in one click.

    The geometry is over-determined - pitch, symbol size, quiet zone and strip
    height all constrain one another - so raising one value routinely makes
    another illegal, and "reduce the symbol or raise the pitch" leaves the user
    to work out which and by how much. A `Fix` carries the arithmetic already
    done: the exact field, the exact value, and a label naming both.

    Deliberately one field. A fix that changed several at once would be a
    guess about intent rather than the single smallest correction that clears
    the finding.
    """

    field: str
    value: float | int
    label: str


@dataclass(frozen=True, slots=True)
class Finding:
    """One validation result, with numbers already substituted into the text."""

    rule_id: str
    severity: Severity
    message: str
    field: str | None = None
    hint: str | None = None
    fix: Fix | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """The complete set of findings for a configuration."""

    findings: tuple[Finding, ...] = ()

    @property
    def max_severity(self) -> Severity:
        if not self.findings:
            return Severity.INFO
        return max(f.severity for f in self.findings)

    @property
    def blocks_export(self) -> bool:
        """ERROR or worse prevents export - a wrong strip is worse than none."""
        return any(f.severity >= Severity.ERROR for f in self.findings)

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity >= Severity.ERROR)

    def for_field(self, path: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.field == path)

    def for_section(self, prefix: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.field and f.field.startswith(prefix + "."))

    def section_severity(self, prefix: str) -> Severity | None:
        found = self.for_section(prefix)
        return max((f.severity for f in found), default=None)

    def counts(self) -> dict[Severity, int]:
        out: dict[Severity, int] = dict.fromkeys(Severity, 0)
        for f in self.findings:
            out[f.severity] += 1
        return out

    def sorted(self) -> tuple[Finding, ...]:
        """Worst first, then by rule ID, for stable display."""
        return tuple(sorted(self.findings, key=lambda f: (-int(f.severity), f.rule_id)))


#: A rule takes the config and the derived geometry (None if it failed to
#: resolve) and yields zero or more findings.
Rule: TypeAlias = Callable[[AopsConfig, "DerivedGeometry | None"], Iterable[Finding]]


def run_rules(
    rules: Sequence[Rule], cfg: AopsConfig, derived: DerivedGeometry | None
) -> ValidationReport:
    """Execute every rule and collect the findings.

    A rule that raises is reported rather than allowed to take down the UI: a
    bug in a validation rule must not stop the engineer working.
    """
    findings: list[Finding] = []
    for rule in rules:
        try:
            findings.extend(rule(cfg, derived))
        except Exception as exc:  # pragma: no cover - defensive
            findings.append(
                Finding(
                    rule_id="INT-001",
                    severity=Severity.WARNING,
                    message=f"Internal validation rule {getattr(rule, '__name__', rule)!r} failed: {exc}",
                )
            )
    return ValidationReport(tuple(findings))
