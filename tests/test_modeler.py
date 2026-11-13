import os, sys, tempfile, unittest
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shipstab import (box_barge, wigley, hull_from_offset_grid, read_offset_csv,
                      hull_from_station_curves, ViewCalibration)


class TestModeler(unittest.TestCase):
    def test_box_barge_exact(self):
        m = box_barge(100, 20, 8).build_mesh()
        self.assertTrue(m.is_watertight())
        self.assertAlmostEqual(m.volume(), 100 * 20 * 8, places=6)
        np.testing.assert_allclose(m.centroid(), [0, 0, 4], atol=1e-9)
        self.assertAlmostEqual(m.surface_area(), 2 * (100 * 20 + 100 * 8 + 20 * 8), places=6)

    def test_wigley_volume(self):
        L, B, T = 100.0, 10.0, 6.25
        m = wigley(L, B, T, 21, 11).build_mesh(x_subdiv=4)
        self.assertTrue(m.is_watertight())
        exact = 4 / 9 * L * B * T
        self.assertLess(abs(m.volume() - exact) / exact, 0.005)
        self.assertAlmostEqual(m.centroid()[0], 0.0, places=6)
        # KB of Wigley at design draft (z measured from keel): 5/8 T below ... check z centroid
        # centroid of area (1 - (z/T)^2) over [-T,0] is at -3T/8
        self.assertAlmostEqual(m.centroid()[2], -3 * T / 8, delta=0.01 * T)

    def test_transom_stern_capped(self):
        # box with a pointed bow (zero width at last station) and a transom stern
        from shipstab import Hull, Section
        secs = [Section(0, [(0, 0), (4, 0), (4, 5)]),
                Section(10, [(0, 0), (4, 0), (4, 5)]),
                Section(20, [(0, 0), (0, 0.001), (0, 5)])]
        m = Hull(secs).build_mesh(x_subdiv=1)
        self.assertTrue(m.is_watertight())
        self.assertGreater(m.volume(), 0)

    def test_ragged_table_sheer(self):
        # deck height 3 at x=0 rising to 4 at x=10, width 6. NaN above the deck.
        xs = [0, 10]
        zs = [0, 1, 2, 3, 4]
        Y = [[3, 3, 3, 3, np.nan], [3, 3, 3, 3, 3]]
        h = hull_from_offset_grid(xs, zs, Y)
        m = h.build_mesh(x_subdiv=1)
        self.assertTrue(m.is_watertight())
        self.assertAlmostEqual(m.volume(), 6 * 10 * 3.5, places=5)

    def test_csv_roundtrip_station_numbers(self):
        L, B, T = 100.0, 10.0, 6.25
        zs = np.linspace(0, T, 6)  # baseline at keel
        stations = np.arange(0, 11)
        xs = stations * L / 10
        rows = ["st," + ",".join(f"{z:g}" for z in zs)]
        for n, x in zip(stations, xs):
            xr = x - L / 2
            y = (B / 2) * (1 - (2 * xr / L) ** 2) * (1 - ((zs - T) / T) ** 2)
            rows.append(f"{n}," + ",".join(f"{v:.6f}" for v in y))
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
            fh.write("\n".join(rows))
        h = read_offset_csv(fh.name, station_mode="number", station_x0=-L / 2, station_spacing=L / 10)
        os.unlink(fh.name)
        m = h.build_mesh()
        self.assertTrue(m.is_watertight())
        exact = 4 / 9 * L * B * T
        self.assertLess(abs(m.volume() - exact) / exact, 0.012)  # coarse 11x6 table

    def test_table_convergence_is_second_order(self):
        L, B, T = 100.0, 10.0, 6.25
        exact = 4 / 9 * L * B * T
        errs = []
        for ns, nw in [(11, 6), (21, 11), (41, 21)]:
            xs = np.linspace(-L / 2, L / 2, ns); zs = np.linspace(0, T, nw)
            Y = np.array([(B / 2) * (1 - (2 * x / L) ** 2) * (1 - ((zs - T) / T) ** 2) for x in xs])
            errs.append(abs(hull_from_offset_grid(xs, zs, Y).build_mesh().volume() - exact) / exact)
        self.assertGreater(errs[0] / errs[1], 3.5)   # ~4x per refinement
        self.assertGreater(errs[1] / errs[2], 3.5)
        self.assertLess(errs[2], 0.001)

    def test_station_curves_orientation(self):
        curves = [(x, [(-3, 5), (-3, 0), (0, 0)]) for x in (0, 10)]  # port side, top-down
        m = hull_from_station_curves(curves).build_mesh(x_subdiv=1)
        self.assertAlmostEqual(m.volume(), 6 * 5 * 10, places=6)

    def test_calibration(self):
        c = ViewCalibration((100, 500), (0, 0), (300, 100), (20, 8), flip_v=True)
        np.testing.assert_allclose(c.to_world([(100, 500), (300, 100), (200, 300)]),
                                   [(0, 0), (20, 8), (10, 4)], atol=1e-9)


class TestViews(unittest.TestCase):
    def test_views_and_report(self):
        from shipstab import views
        h = wigley(100, 10, 6.25)
        m = h.build_mesh()
        for lines in (views.wireframe(h), views.body_plan(h), views.profile(h), views.plan(h),
                      views.project(views.wireframe(h), -35, 25)):
            px = views.fit([np.asarray(l)[:, :2] for l in lines] if lines[0].shape[1] == 3 else lines, 800, 500)
            allp = np.vstack(px)
            self.assertTrue(np.all(allp >= -1e-6) and np.all(allp[:, 0] <= 800 + 1e-6) and np.all(allp[:, 1] <= 500 + 1e-6))
        self.assertIn("Watertight    : yes", views.report(h, m))

    def test_sample_csv_file(self):
        h = read_offset_csv(os.path.join(os.path.dirname(__file__), "..", "examples", "sample_offsets_wigley.csv"),
                            station_mode="number", station_x0=-50, station_spacing=10)
        self.assertTrue(h.build_mesh().is_watertight())


if __name__ == "__main__":
    unittest.main(verbosity=2)
