"""Analytic / parametric hulls. Used for validation and as a starting point
when only main dimensions are known."""
from __future__ import annotations

import numpy as np

from .hull import Hull, Section


def box_barge(L: float, B: float, D: float, n_stations: int = 3) -> Hull:
    """Rectangular barge, baseline at the bottom, deck at z = D."""
    xs = np.linspace(-L / 2, L / 2, n_stations)
    return Hull([Section(x, [(0, 0), (B / 2, 0), (B / 2, D)]) for x in xs], name="box_barge")


def wigley(L: float, B: float, T: float, n_stations: int = 21, n_waterlines: int = 11) -> Hull:
    """Wigley hull up to the design waterline (z = 0 is the waterline here,
    keel at z = -T). Exact displaced volume = 4/9 * L * B * T."""
    xs = np.linspace(-L / 2, L / 2, n_stations)
    zs = np.linspace(-T, 0.0, n_waterlines)
    secs = []
    for x in xs:
        y = (B / 2) * (1 - (2 * x / L) ** 2) * (1 - (zs / T) ** 2)
        secs.append(Section(x, np.column_stack([y, zs])))
    return Hull(secs, name="wigley")
