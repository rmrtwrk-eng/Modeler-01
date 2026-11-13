"""Hull importers. Each one returns a canonical `Hull`.

Implemented & tested
    hull_from_offset_grid     - NumPy grid of half-breadths (stations x waterlines)
    read_offset_csv           - CSV/semicolon offset table -> Hull
    hull_from_station_curves  - list of (x, Nx2 or Nx3 points) station curves -> Hull

    read_knuckle_csv          - longitudinal knuckle/chine lines from CSV

Implemented, needs a DXF test file (ezdxf not available in the build sandbox)
    hull_from_dxf_sections, knuckles_from_dxf

Interfaces only (design in README)
    PdfLinesPlanImporter, RasterLinesPlanImporter
"""
from __future__ import annotations

import csv
from dataclasses import dataclass

import numpy as np

from .hull import Hull, Knuckle, Section

_BLANK = {"", "-", "--", "na", "n/a", "nan", "none"}


# --------------------------------------------------------------------------
# 1. Offset table
# --------------------------------------------------------------------------
def hull_from_offset_grid(xs, zs, half_breadths, name: str = "hull", y_tol: float = 1e-9) -> Hull:
    """xs: (S,) station x positions; zs: (W,) waterline heights above baseline;
    half_breadths: (S, W) array, NaN where the waterline does not intersect the
    hull at that station (below keel, above deck / sheer line).

    Rules applied per station
      * valid cells are sorted by height;
      * if the lowest valid half-breadth is > 0 the section is closed to the
        centreline at that height (flat bottom / bar keel);
      * the highest valid cell is the deck edge at that station.
    """
    xs = np.asarray(xs, float)
    zs = np.asarray(zs, float)
    Y = np.asarray(half_breadths, float)
    if Y.shape != (len(xs), len(zs)):
        raise ValueError(f"grid shape {Y.shape} does not match {len(xs)} stations x {len(zs)} waterlines")
    secs, skipped = [], []
    for x, row in zip(xs, Y):
        ok = np.isfinite(row)
        if ok.sum() == 0:
            skipped.append(float(x))
            continue
        z = zs[ok]
        order = np.argsort(z)
        pts = np.column_stack([row[ok][order], z[order]])
        if len(pts) == 1:  # a single point is a line at best; give it zero height
            pts = np.vstack([pts, pts + [0.0, 1e-6]])
        secs.append(Section(float(x), pts))
    hull = Hull(secs, name=name)
    if skipped:
        hull.warnings.append(f"Stations without any offsets were skipped: {skipped}")
    return hull


def _num(s: str) -> float:
    s = s.strip().replace(",", ".") if s.count(",") == 1 and s.count(".") == 0 else s.strip()
    return float("nan") if s.lower() in _BLANK else float(s)


def read_offset_csv(path: str, layout: str = "stations_rows", delimiter: str = ",",
                    station_mode: str = "x", station_x0: float = 0.0, station_spacing: float = 1.0,
                    scale: float = 1.0, name: str | None = None) -> Hull:
    """Read an offset table.

    layout="stations_rows":   header row = waterline heights, first column = station
    layout="waterlines_rows": header row = stations, first column = waterline heights
    Cell value = half-breadth. Empty cells / '-' / 'NA' = not defined.

    station_mode="x":       first-column / header values are x positions directly
    station_mode="number": values are station numbers; x = x0 + number * spacing
                           (e.g. AP=station 0 -> x0 = x of AP, spacing = Lpp/10)
    scale multiplies every dimension (e.g. 0.001 for mm -> m).
    """
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.reader(fh, delimiter=delimiter) if any(c.strip() for c in r)]
    header = [_num(c) for c in rows[0][1:]]
    first = [_num(r[0]) for r in rows[1:]]
    body = np.array([[_num(c) for c in r[1:1 + len(header)]] + [np.nan] * (len(header) - len(r[1:]))
                     for r in rows[1:]], float)
    if layout == "waterlines_rows":
        xs, zs, Y = np.array(header), np.array(first), body.T
    elif layout == "stations_rows":
        xs, zs, Y = np.array(first), np.array(header), body
    else:
        raise ValueError("layout must be 'stations_rows' or 'waterlines_rows'")
    if station_mode == "number":
        xs = station_x0 + xs * station_spacing
    elif station_mode != "x":
        raise ValueError("station_mode must be 'x' or 'number'")
    return hull_from_offset_grid(xs * scale, zs * scale, Y * scale, name=name or path)


# --------------------------------------------------------------------------
# 2. Explicit station curves (from any 3D source)
# --------------------------------------------------------------------------
def hull_from_station_curves(curves, name: str = "hull") -> Hull:
    """curves: iterable of (x, pts). pts is (N,2) [y,z] or (N,3) [x,y,z].
    Points may be given on either side of the centreline (|y| is used) and in
    either vertical direction (they are ordered keel -> deck)."""
    secs = []
    for x, pts in curves:
        p = np.asarray(pts, float)
        p = p[:, 1:3] if p.shape[1] == 3 else p
        p = np.column_stack([np.abs(p[:, 0]), p[:, 1]])
        if p[0, 1] > p[-1, 1]:
            p = p[::-1]
        secs.append(Section(float(x), p))
    return Hull(secs, name=name)


def _dxf_entities_3d(path: str, layer: str, flatten: float):
    """Yield an (N,3) point array for every curve entity on a DXF layer."""
    import ezdxf  # lazy import: optional dependency

    msp = ezdxf.readfile(path).modelspace()
    for e in msp.query(f'*[layer=="{layer}"]'):
        t = e.dxftype()
        if t == "LINE":
            pts = np.array([tuple(e.dxf.start), tuple(e.dxf.end)])
        elif t == "LWPOLYLINE":
            z = e.dxf.elevation if e.dxf.hasattr("elevation") else 0.0
            pts = np.array([(p[0], p[1], z) for p in e.get_points("xy")])
        elif t == "POLYLINE":
            pts = np.array([tuple(v.dxf.location) for v in e.vertices])
        elif t == "SPLINE":
            pts = np.array([tuple(v) for v in e.flattening(flatten)])
        else:
            continue
        if len(pts) >= 2:
            yield pts


def hull_from_dxf_sections(path: str, layer: str = "STATIONS", x_tol: float = 1e-3,
                           flatten: float = 0.001, name: str | None = None) -> Hull:
    """Read 3D station curves (POLYLINE / LWPOLYLINE / SPLINE / LINE) from a
    DXF layer. A curve is accepted as a station when its x range is below
    x_tol. Requires `ezdxf`."""
    curves = [(float(p[:, 0].mean()), p) for p in _dxf_entities_3d(path, layer, flatten)
              if np.ptp(p[:, 0]) <= x_tol]
    if not curves:
        raise ValueError(f"No station curves found on layer '{layer}' "
                         "(station curves must be 3D curves lying in a plane of constant x)")
    return hull_from_station_curves(curves, name=name or path)


# --------------------------------------------------------------------------
# 2b. Longitudinal knuckle lines
# --------------------------------------------------------------------------
def read_knuckle_csv(path: str, scale: float = 1.0, delimiter: str | None = None) -> list[Knuckle]:
    """Knuckle lines from CSV. Either  name,x,y,z  (several lines in one file,
    rows grouped by name) or plain  x,y,z  (a single line). A header row is
    skipped automatically. Delimiter is auto-detected (, ; tab)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        text = fh.read()
    if delimiter is None:
        first = text.splitlines()[0] if text.strip() else ""
        delimiter = max([",", ";", "\t"], key=first.count)
    rows = [r for r in csv.reader(text.splitlines(), delimiter=delimiter) if any(c.strip() for c in r)]
    groups: dict[str, list] = {}
    for r in rows:
        r = [c.strip() for c in r]
        try:
            if len(r) >= 4:
                name, vals = r[0] or "knuckle", [_num(c) for c in r[1:4]]
            else:
                name, vals = "knuckle", [_num(c) for c in r[:3]]
        except ValueError:
            continue  # header row
        if len(vals) == 3 and all(np.isfinite(vals)):
            groups.setdefault(name, []).append(vals)
    if not groups:
        raise ValueError("No knuckle points found (expected columns: name,x,y,z or x,y,z)")
    return [Knuckle(n, np.array(p) * scale) for n, p in groups.items()]


def knuckles_from_dxf(path: str, layer: str = "KNUCKLES", flatten: float = 0.001) -> list[Knuckle]:
    """Each curve entity on the layer becomes one knuckle line (3D curves, x increasing
    along the line in either direction). Requires `ezdxf`."""
    out = [Knuckle(f"{layer}_{i + 1}", p) for i, p in enumerate(_dxf_entities_3d(path, layer, flatten))]
    if not out:
        raise ValueError(f"No curves found on layer '{layer}'")
    return out


# --------------------------------------------------------------------------
# 3. Drawing-based importers: calibration + interface (to be implemented)
# --------------------------------------------------------------------------
@dataclass
class ViewCalibration:
    """Maps drawing coordinates (PDF points or image pixels) to ship metres for
    ONE view (profile, half-breadth plan or body plan) from two reference points
    with known world coordinates. Axes are assumed orthogonal to the sheet
    (no skew); `flip_v` handles image rows growing downward."""
    p0_drawing: tuple
    p0_world: tuple
    p1_drawing: tuple
    p1_world: tuple
    flip_v: bool = False

    def to_world(self, pts) -> np.ndarray:
        pts = np.asarray(pts, float)
        d0, d1 = np.array(self.p0_drawing, float), np.array(self.p1_drawing, float)
        w0, w1 = np.array(self.p0_world, float), np.array(self.p1_world, float)
        sign = np.array([1.0, -1.0 if self.flip_v else 1.0])
        sc = (w1 - w0) / ((d1 - d0) * sign)  # per-axis scale
        return w0 + (pts - d0) * sign * sc


class PdfLinesPlanImporter:
    """Planned workflow (vector PDF):
    1. extract paths with PyMuPDF (page.get_drawings());
    2. user picks the three views and calibrates each with ViewCalibration;
    3. user classifies picked curves: station / waterline / buttock / sheer /
       deck-at-side / profile / knuckle line;
    4. curves are intersected into a common offset grid (x, z -> y);
    5. consistency report between views, then Hull via hull_from_offset_grid."""

    def load(self, *a, **k):
        raise NotImplementedError("Next milestone")


class RasterLinesPlanImporter(PdfLinesPlanImporter):
    """Same workflow, with a tracing front end: threshold + skeletonise (OpenCV),
    click-to-trace snapping, mandatory user review of every traced curve."""
