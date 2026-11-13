"""Canonical hull model.

Every importer (offset table, DXF, PDF, raster, parametric ...) must end up
producing a `Hull`. Everything downstream (tanks, hydrostatics, stability)
only ever sees the `Hull` / the `TriMesh` built from it.

A hull is a list of transverse `Section`s. Each section stores the starboard
half of the moulded section as a polyline in (y, z), running from the
centreline at the bottom up to the deck edge. The full closed hull is built
symmetrically; the deck is the straight line joining the two deck edges, so
sheer is represented by the z of the last point of each section.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import PchipInterpolator

from .geometry import (TriMesh, allocate_intervals, dedupe, find_corners, polygon_area,
                       resample_arclength, resample_with_corners, triangulate_polygon)


@dataclass
class Section:
    x: float
    pts: np.ndarray  # (n, 2) columns: y >= 0, z ; centreline/bottom -> deck edge

    def __post_init__(self):
        p = dedupe(np.asarray(self.pts, float).reshape(-1, 2))
        if len(p) < 2:
            raise ValueError(f"Section at x={self.x}: need at least 2 distinct points")
        p[:, 0] = np.where(p[:, 0] < 0, 0.0, p[:, 0])  # tolerate tiny negative noise
        if p[0, 0] > 1e-9:  # flat bottom: close to centreline at lowest point
            p = np.vstack([[0.0, p[0, 1]], p])
        self.pts = p


@dataclass
class Hull:
    sections: list[Section]
    name: str = "hull"
    units: str = "m"
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.sections = sorted(self.sections, key=lambda s: s.x)
        xs = np.array([s.x for s in self.sections])
        if len(xs) < 2:
            raise ValueError("A hull needs at least 2 sections")
        if np.any(np.diff(xs) <= 1e-9):
            raise ValueError("Duplicate section positions (x)")

    # ---- basic dimensions -------------------------------------------------
    @property
    def x_range(self):
        return self.sections[0].x, self.sections[-1].x

    @property
    def length(self) -> float:
        a, b = self.x_range
        return b - a

    @property
    def breadth(self) -> float:
        return 2.0 * max(s.pts[:, 0].max() for s in self.sections)

    @property
    def z_range(self):
        zs = np.concatenate([s.pts[:, 1] for s in self.sections])
        return float(zs.min()), float(zs.max())

    # ---- section harmonisation -------------------------------------------
    def _common_sections(self, n_pts: int, corner_deg: float | None):
        pts = [s.pts for s in self.sections]
        counts = {len(p) for p in pts}
        if len(counts) == 1:  # identical topology: use the data exactly as given
            return np.array([s.x for s in self.sections]), np.stack(pts)

        corners = [find_corners(p, corner_deg) for p in pts] if corner_deg else None
        if corners and len({len(c) for c in corners}) == 1 and len(corners[0]) - 1 <= n_pts - 1:
            ncseg = len(corners[0]) - 1
            w = np.zeros(ncseg)
            for p, c in zip(pts, corners):  # average normalised segment lengths
                s = np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]
                seg = s[c[1:]] - s[c[:-1]]
                w += seg / max(seg.sum(), 1e-12)
            alloc = allocate_intervals(np.maximum(w, 1e-6), n_pts - 1)
            out = [resample_with_corners(p, c, alloc) for p, c in zip(pts, corners)]
        else:
            if corner_deg:
                self.warnings.append(
                    "Sections have different numbers of hard corners; resampled by arc length "
                    "(chines/knuckles may be smoothed). Define knuckle lines explicitly.")
            out = [resample_arclength(p, n_pts) for p in pts]
        return np.array([s.x for s in self.sections]), np.stack(out)

    # ---- mesh --------------------------------------------------------------
    def build_mesh(self, n_pts: int = 30, x_subdiv: int = 4,
                   corner_deg: float | None = 15.0, caps: bool = True) -> TriMesh:
        """Closed, watertight, outward-oriented triangle mesh of the moulded hull
        up to the deck line.

        n_pts      points per half-section when sections must be resampled
        x_subdiv   longitudinal subdivisions between data stations (PCHIP,
                   monotone, no overshoot)
        corner_deg turning angle above which a section vertex is kept as a
                   hard corner when resampling (None = pure arc-length)
        """
        X, P = self._common_sections(n_pts, corner_deg)
        S, n, _ = P.shape
        if x_subdiv > 1:
            xn = np.unique(np.concatenate([np.linspace(X[i], X[i + 1], x_subdiv + 1) for i in range(S - 1)]))
            P = PchipInterpolator(X, P.reshape(S, -1), axis=0)(xn).reshape(len(xn), n, 2)
            X, S = xn, len(xn)
        P[:, :, 0] = np.maximum(P[:, :, 0], 0.0)

        # closed loop per station: starboard keel->deck, then port deck->keel
        ys = np.concatenate([P[:, :, 0], -P[:, :0:-1, 0]], axis=1)
        zs = np.concatenate([P[:, :, 1], P[:, :0:-1, 1]], axis=1)
        m = ys.shape[1]
        xs = np.repeat(X[:, None], m, axis=1)
        verts = np.stack([xs, ys, zs], axis=-1).reshape(-1, 3)

        k = np.arange(m)
        faces = []
        for j in range(S - 1):
            a = j * m + k
            b = j * m + (k + 1) % m
            c = (j + 1) * m + (k + 1) % m
            d = (j + 1) * m + k
            faces.append(np.column_stack([a, b, c]))
            faces.append(np.column_stack([a, c, d]))

        scale = max(self.breadth, self.z_range[1] - self.z_range[0], 1.0)
        if caps:
            for j, first in ((0, True), (S - 1, False)):
                poly = np.column_stack([ys[j], zs[j]])
                if abs(polygon_area(poly)) < 1e-9 * scale ** 2:
                    continue  # pointed end (stem/stern line): nothing to close
                tri = np.array(triangulate_polygon(poly)) + j * m
                faces.append(tri[:, ::-1] if first else tri)

        mesh = TriMesh(verts, np.vstack(faces))
        mesh = mesh.welded(tol=1e-9 * scale)
        if mesh.volume() < 0:
            mesh = mesh.flipped()
        return mesh

    # ---- convenience --------------------------------------------------------
    def check(self) -> list[str]:
        """Basic data sanity checks. Returns a list of human-readable issues."""
        issues = list(self.warnings)
        for s in self.sections:
            if np.any(np.diff(s.pts[:, 1]) < -1e-9):
                issues.append(f"x={s.x:g}: section is not monotone in z (tumblehome/bulb or data error?)")
            if s.pts[-1, 0] < 1e-9 and s.pts[:, 0].max() > 1e-9:
                issues.append(f"x={s.x:g}: section ends on the centreline (no deck width)")
        return issues
