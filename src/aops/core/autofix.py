"""Apply every correction the rules can compute, and say what remains.

The validation rules already know how to fix most of what they find - a
`Fix` is a field and a value computed to clear the finding that carries it.
This module runs them to a fixed point: apply the worst finding's fix,
re-derive, re-validate, repeat. One fix routinely changes what the next round
sees - raising the pitch to clear an overlap changes the page fit - which is
why this is a loop over fresh reports and not one pass over a stale one.

THREE WAYS IT ENDS, ALL OF THEM TOLD TO THE USER
------------------------------------------------
* **Clean**: nothing at or above the requested severity is left.
* **Out of fixes**: findings remain but none offers a correction. Some rules
  are deliberately fixless - a missing strip ID cannot be invented, a media
  choice is a purchasing decision, and substituting a different symbology
  behind the user's back is worse than refusing. These come back in
  `unresolved`, each with the rule's own hint for what the human should do.
* **Oscillation**: two rules pull the same field in opposite directions -
  the reader's window wants the pitch smaller, the cutting tolerance wants it
  bigger. Detected by revisiting a configuration already seen (frozen
  hashable configs make this exact, not heuristic). Reported as a conflict,
  because the only honest output for an over-constrained job is to say which
  constraints are fighting.

The whole run is computed against throwaway configurations and returned as
one final config, so the caller can commit it as a single undoable step. An
auto-fixer that leaves fifteen entries on the undo stack turns Ctrl+Z into
archaeology.
"""

from __future__ import annotations

import dataclasses as dc
from dataclasses import dataclass

from aops.core.config import AopsConfig
from aops.core.enums import Severity
from aops.core.rules import ALL_RULES
from aops.core.stats import DerivedGeometry, derive
from aops.core.validation import Finding, ValidationReport, run_rules

#: Rounds before giving up. Generous: real chains settle in two or three, and
#: the cycle detector catches oscillation long before this trips. It exists so
#: a bug in a rule's fix can never hang the interface.
MAX_ROUNDS: int = 24


@dataclass(frozen=True, slots=True)
class FixStep:
    """One correction that was applied, with both sides of the change."""

    rule_id: str
    field: str
    before: object
    after: object
    label: str

    @property
    def sentence(self) -> str:
        return f"[{self.rule_id}] {self.label}  (was {self.before})"


@dataclass(frozen=True, slots=True)
class Unresolved:
    """A finding the fixer left alone, and the honest reason why."""

    rule_id: str
    severity: Severity
    message: str
    reason: str

    @property
    def sentence(self) -> str:
        return f"[{self.rule_id}] {self.message}\n    -> {self.reason}"


@dataclass(frozen=True, slots=True)
class AutofixResult:
    config: AopsConfig
    steps: tuple[FixStep, ...]
    unresolved: tuple[Unresolved, ...]
    #: True when the loop stopped because a configuration repeated.
    oscillated: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.steps)

    @property
    def clean(self) -> bool:
        return not self.unresolved


def _validate(cfg: AopsConfig) -> tuple[ValidationReport, DerivedGeometry | None]:
    try:
        derived = derive(cfg)
    except Exception:
        derived = None
    return run_rules(ALL_RULES, cfg, derived), derived


def _apply(cfg: AopsConfig, field: str, value: object) -> AopsConfig:
    """Write one dotted field, the same way the UI's fix button does."""
    section_name, name = field.split(".", 1)
    section = getattr(cfg, section_name)
    return dc.replace(cfg, **{section_name: dc.replace(section, **{name: value})})


def _actionable(report: ValidationReport, floor: Severity) -> list[Finding]:
    """Findings worth acting on, worst first."""
    return [f for f in report.sorted() if f.severity >= floor]


def autofix(cfg: AopsConfig, *, floor: Severity = Severity.WARNING) -> AutofixResult:
    """Drive the configuration towards clean, one computed fix at a time.

    `floor` is the severity worth acting on. INFO findings are never touched:
    they are notes, and a fixer that "resolves" notes would be optimising the
    issues list rather than the strip.
    """
    steps: list[FixStep] = []
    seen: set[AopsConfig] = {cfg}
    oscillated = False

    for _ in range(MAX_ROUNDS):
        report, _derived = _validate(cfg)
        candidates = [f for f in _actionable(report, floor) if f.fix is not None]

        progressed = False
        for finding in candidates:
            fix = finding.fix
            section_name, name = fix.field.split(".", 1)
            before = getattr(getattr(cfg, section_name), name)
            if before == fix.value:
                # A fix that changes nothing cannot make progress; trying it
                # forever is the one infinite loop the cycle set cannot see.
                continue

            candidate_cfg = _apply(cfg, fix.field, fix.value)
            if candidate_cfg in seen:
                oscillated = True
                continue

            cfg = candidate_cfg
            seen.add(cfg)
            steps.append(FixStep(
                rule_id=finding.rule_id,
                field=fix.field,
                before=before,
                after=fix.value,
                label=fix.label,
            ))
            progressed = True
            break

        if not progressed:
            break

    report, _derived = _validate(cfg)
    unresolved = []
    for finding in _actionable(report, floor):
        if finding.fix is not None and oscillated:
            reason = (
                "its correction was tried and undone by another rule - two "
                "constraints are fighting over this value, and only you can "
                "decide which one gives way (or press Design strip to derive "
                "a geometry that satisfies both)"
            )
        elif finding.fix is not None:
            reason = "its correction makes no change, so something else holds the value"
        else:
            reason = finding.hint or "no automatic correction is offered for this"
        unresolved.append(Unresolved(
            rule_id=finding.rule_id,
            severity=finding.severity,
            message=finding.message,
            reason=reason,
        ))

    return AutofixResult(
        config=cfg,
        steps=tuple(steps),
        unresolved=tuple(unresolved),
        oscillated=oscillated,
    )
