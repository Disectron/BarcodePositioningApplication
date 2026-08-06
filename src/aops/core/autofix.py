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
    severity: Severity = Severity.WARNING

    @property
    def sentence(self) -> str:
        return f"[{self.rule_id}] {self.label}  (was {self.before})"


@dataclass(frozen=True, slots=True)
class Conflict:
    """Two rules pulling one field in opposite directions.

    The challenger is the rule whose fix was refused because applying it would
    revisit a configuration already seen this run; the incumbent is the rule
    whose fix put the field where it is. Both sides carry enough to put a
    question to the user, because a fight between an error and a warning is a
    judgement call the user has said they want to make themselves.
    """

    field: str
    challenger_rule: str
    challenger_severity: Severity
    challenger_message: str
    challenger_value: object
    incumbent_rule: str
    incumbent_severity: Severity
    incumbent_value: object
    #: What the incumbent rule will say if the challenger's value is taken -
    #: the concrete cost of ruling that way, quoted rather than alluded to.
    incumbent_message: str = ""

    @property
    def sentence(self) -> str:
        return (
            f"[{self.challenger_rule}] wants {self.field} = "
            f"{self.challenger_value}, but [{self.incumbent_rule}] set it to "
            f"{self.incumbent_value} - the two pull in opposite directions."
        )


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
    #: The specific fights behind any oscillation, for the UI to put to the user.
    conflicts: tuple[Conflict, ...] = ()

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
    conflicts: dict[tuple[str, str], Conflict] = {}
    oscillated = False

    def last_setter(field: str) -> FixStep | None:
        for step in reversed(steps):
            if step.field == field:
                return step
        return None

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
                # Name the fight: this fix versus whichever rule put the field
                # where it is. "The user's own value" is a legitimate incumbent
                # too - a hand-set field the fixer keeps bouncing off.
                incumbent = last_setter(fix.field)
                key = (fix.field, finding.rule_id)
                if key not in conflicts:
                    # What does the incumbent rule say at the challenger's
                    # value? Validating the refused candidate answers with the
                    # incumbent's own words - "cutting tolerance drops to
                    # 1.31 mm" - which is the concrete cost of ruling that way.
                    incumbent_msg = ""
                    if incumbent is not None:
                        candidate_report, _ = _validate(candidate_cfg)
                        incumbent_msg = next(
                            (f.message for f in candidate_report.findings
                             if f.rule_id == incumbent.rule_id),
                            "",
                        )
                    conflicts[key] = Conflict(
                        field=fix.field,
                        challenger_rule=finding.rule_id,
                        challenger_severity=finding.severity,
                        challenger_message=finding.message,
                        challenger_value=fix.value,
                        incumbent_rule=(
                            incumbent.rule_id if incumbent else "your setting"
                        ),
                        incumbent_severity=(
                            incumbent.severity if incumbent else Severity.INFO
                        ),
                        incumbent_value=before,
                        incumbent_message=incumbent_msg,
                    )
                continue

            cfg = candidate_cfg
            seen.add(cfg)
            steps.append(FixStep(
                rule_id=finding.rule_id,
                field=fix.field,
                before=before,
                after=fix.value,
                label=fix.label,
                severity=finding.severity,
            ))
            progressed = True
            break

        if not progressed:
            break

    report, _derived = _validate(cfg)
    unresolved = []
    for finding in _actionable(report, floor):
        fight = next(
            (c for c in conflicts.values() if c.challenger_rule == finding.rule_id),
            None,
        )
        if fight is not None:
            reason = (
                f"its correction was undone by [{fight.incumbent_rule}] pulling "
                f"{fight.field} the other way - only you can decide which gives "
                f"way, or press Design strip to derive a geometry satisfying both"
            )
        elif finding.fix is not None and oscillated:
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
        conflicts=tuple(conflicts.values()),
    )
