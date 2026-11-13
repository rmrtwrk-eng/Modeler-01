"""GUI-independent view geometry: wireframe lines and 2D projections.
Every function returns plain lists of Nx2 numpy arrays in 'view units';
`fit` maps them to canvas pixels."""
from __future__ import annotations

import numpy as np

from .hull import Hull


def wireframe(hull: Hull, n_pts: int = 24, long_lines: int = 8):
    """3D polylines: every station (both sides, closed over the deck line) plus
    longitudinal lines through selected section points."""
    X, P = hull._common_sections(n_pts, 15.0)
    S, n, _ = P.shape
    lines = []
    for j in range(S):
        stbd = np.column_stack([np.full(n, X[j]), P[j, :, 0], P[j, :, 1]])
        port = stbd * [1, -1, 1]
        lines.append(np.vstack([port[::-1], stbd[1:]]))
    for i in np.unique(np.linspace(1, n - 1, long_lines).astype(int)):
        for sgn in (1, -1):
            lines.append(np.column_stack([X, sgn * P[:, i, 0], P[:, i, 1]]))
    return lines


def knuckle_lines(hull: Hull):
    """3D polylines of the knuckle lines, both sides."""
    out = []
    for k in hull.knuckles:
        out.append(k.pts.copy())
        out.append(k.pts * [1, -1, 1])
    return out


def project(lines3d, yaw_deg: float, pitch_deg: float):
    """Orthographic projection. x forward, y starboard, z up."""
    a, b = np.radians(yaw_deg), np.radians(pitch_deg)
    ca, sa, cb, sb = np.cos(a), np.sin(a), np.cos(b), np.sin(b)
    out = []
    for L in lines3d:
        x, y, z = L[:, 0], L[:, 1], L[:, 2]
        xr = x * ca - y * sa          # rotate about vertical axis
        yr = x * sa + y * ca
        out.append(np.column_stack([xr, z * cb + yr * sb]))
    return out


def body_plan(hull: Hull):
    """Stations of the forward half on the right, aft half on the left."""
    xm = 0.5 * sum(hull.x_range)
    lines = []
    for s in hull.sections:
        y = s.pts[:, 0] * (1 if s.x >= xm else -1)
        lines.append(np.column_stack([y, s.pts[:, 1]]))
    lines.append(np.array([[0, hull.z_range[0]], [0, hull.z_range[1]]]))  # centreline
    return lines


def profile(hull: Hull):
    """Keel line, deck-edge (sheer) line, end closures, station ticks."""
    xs = np.array([s.x for s in hull.sections])
    keel = np.array([s.pts[:, 1].min() for s in hull.sections])
    deck = np.array([s.pts[-1, 1] for s in hull.sections])
    lines = [np.column_stack([xs, keel]), np.column_stack([xs, deck])]
    lines += [np.array([[x, k], [x, d]]) for x, k, d in zip(xs, keel, deck)]
    return lines


def plan(hull: Hull):
    """Half-breadth plan: deck-edge outline (both sides) and max-breadth lines."""
    xs = np.array([s.x for s in hull.sections])
    ydeck = np.array([s.pts[-1, 0] for s in hull.sections])
    ymax = np.array([s.pts[:, 0].max() for s in hull.sections])
    lines = []
    for sgn in (1, -1):
        lines.append(np.column_stack([xs, sgn * ydeck]))
        lines.append(np.column_stack([xs, sgn * ymax]))
    lines += [np.array([[x, -m], [x, m]]) for x, m in zip(xs, ymax)]
    return lines


def fit(lines2d, width: int, height: int, margin: int = 30, equal_aspect: bool = True,
        flip_y: bool = True):
    """Scale/translate polylines into pixel coordinates (canvas y grows down)."""
    allp = np.vstack(lines2d)
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)
    sx = (width - 2 * margin) / span[0]
    sy = (height - 2 * margin) / span[1]
    if equal_aspect:
        sx = sy = min(sx, sy)
    ox = (width - span[0] * sx) / 2
    oy = (height - span[1] * sy) / 2
    out = []
    for L in lines2d:
        px = ox + (L[:, 0] - lo[0]) * sx
        py = oy + (L[:, 1] - lo[1]) * sy
        if flip_y:
            py = height - py
        out.append(np.column_stack([px, py]))
    return out


def report(hull: Hull, mesh) -> str:
    z0, z1 = hull.z_range
    c = mesh.centroid()
    issues = hull.check()
    txt = [
        f"Name            : {hull.name}",
        f"Sections        : {len(hull.sections)}",
        f"Length (x range): {hull.length:.3f}  [{hull.x_range[0]:.3f} .. {hull.x_range[1]:.3f}]",
        f"Max breadth     : {hull.breadth:.3f}",
        f"Z range         : {z0:.3f} .. {z1:.3f}",
        "",
        "Closed moulded hull up to the deck line (NOT hydrostatics):",
        f"  Volume        : {mesh.volume():.3f}",
        f"  Centroid x,y,z: {c[0]:.3f}, {c[1]:.3f}, {c[2]:.3f}",
        f"  Surface area  : {mesh.surface_area():.3f}",
        f"  Watertight    : {'yes' if mesh.is_watertight() else 'NO - check input data'}",
        f"  Triangles     : {len(mesh.faces)}",
        f"Knuckle lines   : {len(hull.knuckles)}" + (
            "  (" + ", ".join(k.name for k in hull.knuckles) + ")" if hull.knuckles else ""),
        "",
        "Checks / warnings:" if issues else "Checks: no issues found.",
    ]
    txt += [f"  - {i}" for i in issues]
    return "\n".join(txt)
