"""`ModuleMatrix` - the backend-neutral representation of an encoded symbol.

This type lives in `core`, not in `symbols`, on purpose. `core.drawlist` needs
to reference a symbol primitive, and if the matrix type lived in `symbols` then
`core` would depend on `symbols`, breaking the inward-only dependency rule that
`tests/test_layering.py` enforces.

The rectangle decomposition matters more than it looks. Drawing a 16x16 symbol
as 256 individual filled squares produces a large PDF *and* hairline seams where
adjacent same-colour rectangles meet, because PDF viewers anti-alias each edge
independently. Merging runs into maximal rectangles typically cuts 256 draws to
about 35 and removes the seams.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModuleMatrix:
    """A square (or rectangular) grid of dark/light modules.

    `bits` is row-major, one byte per module, 1 = dark. A 16x16 symbol is 256
    bytes, so caching thousands of these costs a couple of megabytes.
    """

    rows: int
    cols: int
    bits: bytes
    symbology: str
    payload: str
    quiet_modules: int

    def __post_init__(self) -> None:
        if len(self.bits) != self.rows * self.cols:
            raise ValueError(
                f"ModuleMatrix bits length {len(self.bits)} does not match "
                f"{self.rows}x{self.cols} = {self.rows * self.cols}"
            )

    def dark(self, row: int, col: int) -> bool:
        return bool(self.bits[row * self.cols + col])

    @property
    def key(self) -> tuple[str, str]:
        return (self.symbology, self.payload)

    @property
    def dark_count(self) -> int:
        return sum(self.bits)

    def to_ascii(self, dark: str = "##", light: str = "  ") -> str:
        """Render as text. Used by the CLI inspection tool and by test failures."""
        lines = []
        for r in range(self.rows):
            lines.append("".join(dark if self.dark(r, c) else light for c in range(self.cols)))
        return "\n".join(lines)


def to_rects(matrix: ModuleMatrix) -> tuple[tuple[int, int, int, int], ...]:
    """Decompose the dark modules into maximal rectangles.

    Returns tuples of ``(col, row, width, height)`` in module units.

    Strategy: encode each row as horizontal runs, then merge a run with the run
    directly above it when they have identical start and width. This is not the
    theoretically optimal decomposition, but it is O(rows x cols), deterministic,
    and captures the large solid blocks that dominate a Data Matrix.
    """
    rects: list[tuple[int, int, int, int]] = []
    # Open runs from the previous row, keyed by (start_col, width) -> (row, height)
    open_runs: dict[tuple[int, int], tuple[int, int]] = {}

    for r in range(matrix.rows):
        row_runs: dict[tuple[int, int], tuple[int, int]] = {}
        c = 0
        while c < matrix.cols:
            if matrix.dark(r, c):
                start = c
                while c < matrix.cols and matrix.dark(r, c):
                    c += 1
                width = c - start
                key = (start, width)
                if key in open_runs:
                    top, height = open_runs.pop(key)
                    row_runs[key] = (top, height + 1)
                else:
                    row_runs[key] = (r, 1)
            else:
                c += 1

        # Any run not continued on this row is complete.
        for (start, width), (top, height) in open_runs.items():
            rects.append((start, top, width, height))
        open_runs = row_runs

    for (start, width), (top, height) in open_runs.items():
        rects.append((start, top, width, height))

    return tuple(sorted(rects))


def matrix_from_rows(
    rows: list[list[bool]], *, symbology: str, payload: str, quiet_modules: int
) -> ModuleMatrix:
    """Build a `ModuleMatrix` from a list-of-lists of booleans."""
    if not rows or not rows[0]:
        raise ValueError("Cannot build a ModuleMatrix from an empty grid.")
    n_rows, n_cols = len(rows), len(rows[0])
    if any(len(r) != n_cols for r in rows):
        raise ValueError("ModuleMatrix rows must all be the same length.")
    bits = bytes(1 if value else 0 for row in rows for value in row)
    return ModuleMatrix(
        rows=n_rows,
        cols=n_cols,
        bits=bits,
        symbology=symbology,
        payload=payload,
        quiet_modules=quiet_modules,
    )
