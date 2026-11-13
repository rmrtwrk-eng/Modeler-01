# shipstab – Chapter 1: Hull modeler

Requires Python 3.10+, `numpy`, `scipy`. Optional: `ezdxf` (DXF import).
Run tests: `python tests/test_modeler.py` – demo: `python examples/demo.py`.

Coordinates: x forward, y to starboard, z up from baseline.

## Architecture

    importers  ->  Hull (list of Sections)  ->  build_mesh()  ->  TriMesh
    (any source)   canonical model             watertight         volume, centroid,
                                               closed hull        OBJ/STL export

A `Section` is the starboard half of a transverse section (y, z) from the
centreline at the bottom to the deck edge. Deck = straight line between the two
deck edges, so sheer lives in the z of the last point. Loft between stations
uses monotone PCHIP (no overshoot). End sections with zero width (stem) are not
capped; sections with area (transom) are capped by ear-clipping.

## Status of input methods

| Method | Status |
|---|---|
| Offset grid / CSV (stations x waterlines, ragged tops/bottoms, station numbers or x, mm/m scale) | done, tested |
| Explicit station curves (any 3D source, either side, either direction) | done, tested |
| Parametric: box barge, Wigley | done, tested |
| DXF station curves (3D polylines/splines on a layer) | written, **untested** (no ezdxf / sample file here) |
| Vector PDF lines plan | interface + `ViewCalibration` (tested); extraction/classification next |
| Raster lines plan | interface only |
| Mesh import (STL/OBJ), IGES/STEP, Rhino 3dm | not started |

## Validation so far

* Box barge: volume, centroid, surface area exact.
* Wigley hull from a table: second-order convergence of volume
  (-1.06 % -> -0.27 % -> -0.07 % -> -0.02 % at 11x6, 21x11, 41x21, 81x41 grid),
  LCB = 0, VCB at -3T/8 within 1 %.
* All meshes are watertight and consistently oriented.

## Known limitations (intentional, next items)

1. **Knuckles/chines** are preserved at data stations. If chines run *between*
   stations, or section corner counts differ, resampling falls back to
   arc length and a warning is recorded in `Hull.warnings`. Fix: explicit
   longitudinal knuckle/chine lines as part of the model.
2. No fairing tools yet (curvature check of stations/waterlines/buttocks,
   cross-view consistency of the three curve families).
3. Single moulded hull only: no bulbous-bow transitions with vertical stem
   overhang beyond what sections can express, no appendages, no shell
   thickness (moulded/ extreme displacement option to come).
4. Hull is closed at the deck line. Superstructure/buoyant volumes above the
   deck are future items (needed for large-angle stability).
5. Tolerance of the table-based model is limited by the table itself: use the
   convergence test above as a guide for how coarse is too coarse.

## Suggested next steps for the modeler

1. Knuckle lines + fairing/consistency report.
2. Vector PDF importer with view calibration and curve classification UI.
3. Raster tracing assistant.
4. STL/OBJ/IGES import and fit to sections.
5. Parametric generator from main dimensions + coefficients (Cb, Cp, LCB).

## Desktop application (Windows .exe)

`shipstab_app.py` starts the GUI (tkinter): import buttons (offset CSV with an options
dialog, DXF), example hulls, 3D wireframe (drag to rotate), body plan, profile,
half-breadth plan, report tab, OBJ/STL export.

Build the .exe **on a Windows PC** (PyInstaller cannot cross-compile):

1. Install Python 3.10+ from python.org (tick "Add to PATH"; tkinter is included).
2. Double-click `build_exe.bat`  ->  `dist\ShipStab.exe` (single file, ~100-150 MB because of scipy).

Try it with `examples\sample_offsets_wigley.csv`: layout `stations_rows`, delimiter comma,
station column = `number`, x of station 0 = `-50`, spacing = `10`, scale = `1`.
Expected: Wigley hull, volume ~2.77e3, watertight.

Status: the drawing/report logic (`views.py`) is unit-tested; the tkinter window code
(`gui.py`) compiles but has not been run on a screen yet.

## Automatic .exe build (GitHub Actions)

`.github/workflows/build-exe.yml` builds `ShipStab.exe` on a Windows runner.

1. Create a GitHub repository and push the contents of this folder (the folder
   containing `shipstab_app.py` must be the repository root).
2. Open the **Actions** tab. The build runs on every push; you can also start it
   with **Run workflow**.
3. When it finishes, download `ShipStab-windows-exe` from the run's **Artifacts**.
4. For a permanent download link: `git tag v0.1.0 && git push origin v0.1.0` -
   the exe is then attached to a GitHub Release.

The workflow runs the unit tests first, so a broken change will not produce an exe.
