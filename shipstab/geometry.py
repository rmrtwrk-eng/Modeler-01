"""Low-level geometry: polyline utilities, polygon triangulation, triangle mesh.

Coordinate convention used everywhere in shipstab
-------------------------------------------------
x : longitudinal, positive forward
y : transverse, positive to starboard
z : vertical, positive up (measured from the baseline, i.e. keel line)
"""
from __future__ import annotations

import numpy as np

# --------------------------------------------------------------------------
# Polylines (2D, in the y-z plane)
# --------------------------------------------------------------------------


def dedupe(p: np.ndarray, tol: float = 1e-9) -> np.ndarray:
    """Remove consecutive duplicate points."""
    p = np.asarray(p, float)
    keep = [0]
    for i in range(1, len(p)):
        if np.hypot(*(p[i] - p[keep[-1]])) > tol:
            keep.append(i)
    return p[keep]


def cumulative_length(p: np.ndarray) -> np.ndarray:
    return np.r_[0.0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]


def find_corners(p: np.ndarray, angle_deg: float) -> list[int]:
    """Indices of hard corners (turning angle > angle_deg), incl. both ends."""
    idx = [0]
    v = np.diff(p, axis=0)
    for i in range(1, len(p) - 1):
        a, b = v[i - 1], v[i]
        na, nb = np.hypot(*a), np.hypot(*b)
        if na < 1e-12 or nb < 1e-12:
            continue
        cosang = np.clip(np.dot(a, b) / (na * nb), -1, 1)
        if np.degrees(np.arccos(cosang)) > angle_deg:
            idx.append(i)
    idx.append(len(p) - 1)
    return idx


def resample_arclength(p: np.ndarray, n: int) -> np.ndarray:
    """Resample polyline to n points, uniform in arc length."""
    p = dedupe(p)
    s = cumulative_length(p)
    t = np.linspace(0, s[-1], n)
    return np.column_stack([np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1])])


def resample_with_corners(p: np.ndarray, corners: list[int], alloc: np.ndarray) -> np.ndarray:
    """Resample so that each corner-to-corner segment gets alloc[k] intervals.
    Corner points are reproduced exactly."""
    s = cumulative_length(p)
    out = []
    for k in range(len(corners) - 1):
        a, b = s[corners[k]], s[corners[k + 1]]
        t = np.linspace(a, b, int(alloc[k]) + 1)
        if k < len(corners) - 2:
            t = t[:-1]
        out.append(np.column_stack([np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1])]))
    return np.vstack(out)


def allocate_intervals(weights: np.ndarray, total: int) -> np.ndarray:
    """Split `total` intervals among segments (>=1 each), proportional to weights."""
    k = len(weights)
    alloc = np.ones(k, int)
    extra = total - k
    share = weights / weights.sum() * extra
    base = np.floor(share).astype(int)
    alloc += base
    rem = extra - base.sum()
    if rem > 0:
        alloc[np.argsort(-(share - base))[:rem]] += 1
    return alloc


# --------------------------------------------------------------------------
# Polygon triangulation (ear clipping) for section end caps
# --------------------------------------------------------------------------


def polygon_area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def triangulate_polygon(poly: np.ndarray) -> list[tuple[int, int, int]]:
    """Ear-clipping triangulation of a simple polygon (any orientation).

    Triangles are returned in the polygon's own traversal direction. Collinear
    vertices produce zero-area triangles on purpose: this keeps the cap
    topologically watertight against the hull strip (no T-junctions)."""
    poly = np.asarray(poly, float)
    m = len(poly)
    s = 1.0 if polygon_area(poly) >= 0 else -1.0
    scale = max(np.ptp(poly[:, 0]), np.ptp(poly[:, 1]), 1e-12) ** 2
    tol = 1e-12 * scale

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    idx = list(range(m))
    tris: list[tuple[int, int, int]] = []
    while len(idx) > 3:
        n = len(idx)
        found, fallback = None, None
        for t in range(n):
            i0, i1, i2 = idx[t - 1], idx[t], idx[(t + 1) % n]
            c = s * cross(poly[i0], poly[i1], poly[i2])
            if c < -tol:
                continue  # reflex
            if c <= tol:
                if fallback is None:
                    fallback = t
                continue
            a, b, cc = poly[i0], poly[i1], poly[i2]
            ok = True
            for q in idx:
                if q in (i0, i1, i2):
                    continue
                p = poly[q]
                if (s * cross(a, b, p) > tol and s * cross(b, cc, p) > tol
                        and s * cross(cc, a, p) > tol):
                    ok = False
                    break
            if ok:
                found = t
                break
        if found is None:
            found = fallback if fallback is not None else 0
        i0, i1, i2 = idx[found - 1], idx[found], idx[(found + 1) % n]
        tris.append((i0, i1, i2))
        del idx[found]
    tris.append((idx[0], idx[1], idx[2]))
    return tris


# --------------------------------------------------------------------------
# Triangle mesh
# --------------------------------------------------------------------------


class TriMesh:
    def __init__(self, vertices: np.ndarray, faces: np.ndarray):
        self.vertices = np.asarray(vertices, float)
        self.faces = np.asarray(faces, int)

    # -- integral properties (divergence theorem) --------------------------
    def _tets(self):
        v = self.vertices[self.faces]
        vol6 = np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2]))
        return v, vol6 / 6.0

    def volume(self) -> float:
        return float(self._tets()[1].sum())

    def centroid(self) -> np.ndarray:
        v, vol = self._tets()
        c = (v.sum(axis=1) / 4.0) * vol[:, None]
        return c.sum(axis=0) / vol.sum()

    def surface_area(self) -> float:
        v = self.vertices[self.faces]
        return float(0.5 * np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1).sum())

    def bounds(self):
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    # -- topology ----------------------------------------------------------
    def is_watertight(self) -> bool:
        """Closed, consistently oriented 2-manifold test: every directed edge
        occurs exactly once and has exactly one opposite partner."""
        f = self.faces
        a = np.concatenate([f[:, 0], f[:, 1], f[:, 2]])
        b = np.concatenate([f[:, 1], f[:, 2], f[:, 0]])
        nv = len(self.vertices)
        fwd = a.astype(np.int64) * nv + b
        rev = b.astype(np.int64) * nv + a
        if len(np.unique(fwd)) != len(fwd):
            return False
        return bool(np.array_equal(np.sort(fwd), np.sort(rev)))

    def welded(self, tol: float) -> "TriMesh":
        key = np.round(self.vertices / tol).astype(np.int64)
        _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
        inv = np.asarray(inv).reshape(-1)
        faces = inv[self.faces]
        ok = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
        used = np.unique(faces[ok])
        remap = -np.ones(len(first), int)
        remap[used] = np.arange(len(used))
        return TriMesh(self.vertices[first][used], remap[faces[ok]])

    def flipped(self) -> "TriMesh":
        return TriMesh(self.vertices, self.faces[:, ::-1])

    # -- export ------------------------------------------------------------
    def to_obj(self, path: str) -> None:
        with open(path, "w") as fh:
            for v in self.vertices:
                fh.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            for f in self.faces:
                fh.write(f"f {f[0]+1} {f[1]+1} {f[2]+1}\n")

    def to_stl(self, path: str, name: str = "hull") -> None:
        v = self.vertices[self.faces]
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
        with open(path, "w") as fh:
            fh.write(f"solid {name}\n")
            for tri, nn in zip(v, n):
                fh.write(f" facet normal {nn[0]:.6e} {nn[1]:.6e} {nn[2]:.6e}\n  outer loop\n")
                for p in tri:
                    fh.write(f"   vertex {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")
                fh.write("  endloop\n endfacet\n")
            fh.write(f"endsolid {name}\n")
