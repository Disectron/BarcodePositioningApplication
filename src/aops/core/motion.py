"""Reading the strip while the axis is moving.

Everything else in this project treats the strip as a static object: get the
geometry right, get it printed accurately, mount it straight. But the whole
purpose of a position tape is to be read by a machine that is *moving*, and
motion imposes two limits that have nothing to do with the geometry being
correct. Both are speeds, and the lower one wins.

THE BLUR LIMIT
--------------
During the reader's exposure the code travels, and the image smears by that
distance. Newland's own guidance for the NVF230 family (user guide S7.8,
"Enhancing Motion Tolerance") gives the exposure to use as

    t [us] = 25.4 x (code width in mils) / v [m/s]

which reduces, once the units are unpicked, to a statement about smear:

    smear = v x t = one module width

So the vendor's recommended exposure is the one that smears the image by
exactly one module, and that is the tolerance being spent. Inverted, it gives
the speed a given exposure can survive:

    v_max = module / exposure

A concrete case, and the reason this belongs in the software: a 1.000 mm module
at the reader's default 1000 us exposure tolerates **1.0 m/s**. Nothing in the
strip design says so, and nobody discovers it until the machine runs.

Bigger modules tolerate more speed, linearly. That makes module size a
*motion* decision as much as a print-resolution one, which is not obvious from
either end on its own.

THE FRAME LIMIT
---------------
The reader captures discrete frames. The NVF230's burst-mode length formula
(user guide S5.1.2) is

    length = scanning range [mm] / speed [mm/s] x 1000 / 20

which is "how many 20 ms frame intervals does the code spend in view" - so the
camera takes one frame every 20 ms, i.e. 50 per second. A code that crosses the
field of view in less than one frame interval can be missed entirely, however
sharp it would have been:

    v_max = field of view / (frames wanted x frame interval)

One frame is the bare minimum and no redundancy at all. Asking for two or three
is what makes a read reliable, and it costs speed proportionally.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not model illumination. A shorter exposure needs more light or more
gain, and past some point the image is too dark to decode whatever the blur
maths says - the NVF230's exposure floor is 60 us, but reaching it in a real
machine may need lighting this project knows nothing about. So the blur limit
is an upper bound on what is achievable, not a promise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: Exposure range the NVF230 accepts, in microseconds (user guide S4.7.1).
#: Other readers differ; these are the defaults the fields start from.
EXPOSURE_MIN_US: Final[int] = 60
EXPOSURE_MAX_US: Final[int] = 60_000
EXPOSURE_DEFAULT_US: Final[int] = 1_000

#: Frame interval implied by the burst-mode formula: one capture per 20 ms.
FRAME_INTERVAL_MS: Final[float] = 20.0

#: Smear the vendor's exposure formula spends, in modules. Deriving this rather
#: than hard-coding "one module" in the arithmetic keeps the assumption visible.
SMEAR_BUDGET_MODULES: Final[float] = 1.0


@dataclass(frozen=True, slots=True)
class MotionLimits:
    """The two speed ceilings, and which one binds.

    Speeds are millimetres per second throughout - the unit a servo is
    commissioned in. `0.0` for either limit means "not computable from what is
    known", not "no limit".
    """

    module_mm: float
    exposure_us: int
    fov_mm: float
    frames_wanted: int
    frame_interval_ms: float
    #: Fastest the axis can move before the image smears past one module.
    blur_speed_mm_per_s: float
    #: Fastest the axis can move while a code still lands in enough frames.
    frame_speed_mm_per_s: float
    #: What the machine is actually asked to do. 0.0 means unspecified.
    requested_speed_mm_per_s: float

    @property
    def max_speed_mm_per_s(self) -> float:
        """The binding limit: the lower of the two, ignoring uncomputable ones."""
        limits = [v for v in (self.blur_speed_mm_per_s, self.frame_speed_mm_per_s) if v > 0.0]
        return min(limits) if limits else 0.0

    @property
    def limited_by(self) -> str:
        """Which ceiling binds, named for a message. Empty when neither is known."""
        top = self.max_speed_mm_per_s
        if top <= 0.0:
            return ""
        if self.blur_speed_mm_per_s > 0.0 and top == self.blur_speed_mm_per_s:
            return "exposure"
        return "frame rate"

    @property
    def is_specified(self) -> bool:
        return self.requested_speed_mm_per_s > 0.0

    @property
    def fits(self) -> bool:
        """True when the requested speed is inside the binding limit."""
        top = self.max_speed_mm_per_s
        return not self.is_specified or top <= 0.0 or self.requested_speed_mm_per_s <= top

    @property
    def headroom(self) -> float:
        """Ratio of the limit to the requested speed. Above 1.0 has margin."""
        if not self.is_specified or self.max_speed_mm_per_s <= 0.0:
            return 0.0
        return self.max_speed_mm_per_s / self.requested_speed_mm_per_s

    @property
    def exposure_needed_us(self) -> float:
        """Exposure the requested speed would need to stay inside the blur budget."""
        return exposure_for_speed(self.module_mm, self.requested_speed_mm_per_s)

    @property
    def exposure_is_reachable(self) -> bool:
        """True when the needed exposure is one the reader can actually be set to."""
        needed = self.exposure_needed_us
        return needed > 0.0 and needed >= EXPOSURE_MIN_US

    @property
    def smear_mm(self) -> float:
        """How far the code travels during one exposure at the requested speed."""
        if not self.is_specified or self.exposure_us <= 0:
            return 0.0
        return self.requested_speed_mm_per_s * (self.exposure_us / 1e6)

    @property
    def smear_modules(self) -> float:
        """The smear as a multiple of the module size - the number that decides."""
        if self.module_mm <= 0.0:
            return 0.0
        return self.smear_mm / self.module_mm


def blur_limited_speed(module_mm: float, exposure_us: int) -> float:
    """Fastest travel whose smear stays within the module-size budget, in mm/s.

    Equivalent to the vendor's exposure formula, rearranged for speed. Stated
    in millimetres and microseconds rather than mils and metres per second,
    because that is what the rest of this project works in.
    """
    if module_mm <= 0.0 or exposure_us <= 0:
        return 0.0
    return SMEAR_BUDGET_MODULES * module_mm / (exposure_us / 1e6)


def exposure_for_speed(module_mm: float, speed_mm_per_s: float) -> float:
    """Longest exposure that keeps smear within one module at this speed, in us."""
    if module_mm <= 0.0 or speed_mm_per_s <= 0.0:
        return 0.0
    return SMEAR_BUDGET_MODULES * module_mm / speed_mm_per_s * 1e6


def frame_limited_speed(
    fov_mm: float, frames_wanted: int, frame_interval_ms: float = FRAME_INTERVAL_MS
) -> float:
    """Fastest travel that still puts a code in `frames_wanted` frames, in mm/s.

    A code is in view for `fov / v` seconds. Requiring that to cover a whole
    number of frame intervals is what bounds the speed.
    """
    if fov_mm <= 0.0 or frames_wanted <= 0 or frame_interval_ms <= 0.0:
        return 0.0
    return fov_mm / (frames_wanted * frame_interval_ms / 1000.0)


def frames_on_a_code(
    fov_mm: float, speed_mm_per_s: float, frame_interval_ms: float = FRAME_INTERVAL_MS
) -> float:
    """How many frames a code is caught in at this speed. Fractional on purpose.

    Below 1.0 the code can pass through unseen; the fraction is roughly the
    probability of catching it, which is a more useful thing to report than a
    floor of zero.
    """
    if speed_mm_per_s <= 0.0 or fov_mm <= 0.0 or frame_interval_ms <= 0.0:
        return 0.0
    dwell_ms = fov_mm / speed_mm_per_s * 1000.0
    return dwell_ms / frame_interval_ms


def motion_limits(
    *,
    module_mm: float,
    fov_mm: float,
    exposure_us: int = EXPOSURE_DEFAULT_US,
    frames_wanted: int = 1,
    frame_interval_ms: float = FRAME_INTERVAL_MS,
    requested_speed_mm_per_s: float = 0.0,
) -> MotionLimits:
    """Both speed ceilings for one geometry and reader setting."""
    return MotionLimits(
        module_mm=module_mm,
        exposure_us=exposure_us,
        fov_mm=fov_mm,
        frames_wanted=max(1, frames_wanted),
        frame_interval_ms=frame_interval_ms,
        blur_speed_mm_per_s=blur_limited_speed(module_mm, exposure_us),
        frame_speed_mm_per_s=frame_limited_speed(
            fov_mm, max(1, frames_wanted), frame_interval_ms
        ),
        requested_speed_mm_per_s=requested_speed_mm_per_s,
    )
