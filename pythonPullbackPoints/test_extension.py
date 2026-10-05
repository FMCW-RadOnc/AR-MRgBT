import csv
import io
from pathlib import Path
import sys
import uuid
import unittest
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from pullback_core import DISTANCE_COLUMNS, TRACKER_COLUMNS, read_offsets, to_dicom


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / ("test_tmp_" + uuid.uuid4().hex)
        self.directory.mkdir()
        def cleanup():
            for path in self.directory.iterdir():
                if path.is_dir():
                    for child in path.iterdir():
                        child.unlink()
                    path.rmdir()
                    continue
                path.unlink()
            self.directory.rmdir()
        self.addCleanup(cleanup)
        self.path = self.directory / "points.csv"

    def csv(self, columns, rows):
        with self.path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Needle", "Timestamp"] + list(columns))
            writer.writerows(rows)

    def test_signs_nonzero_anchor(self):
        self.assertEqual(to_dicom((100, 200, 300), (5, -6, 7)), (95, 206, 307))

    def test_duplicates_selection_and_blanks(self):
        self.csv(DISTANCE_COLUMNS, [["A", "12:00:00.001", 5, 6, 7]] * 2 +
                 [["B", "12:00:00.002", 1, 2, 3], ["A", "12:00:00.003", "", "", ""]])
        samples, skipped = read_offsets(self.path, "A")
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0][2], (5, 6, 7))
        self.assertEqual(skipped, 1)

    def test_legacy_requires_explicit_target(self):
        self.csv(TRACKER_COLUMNS, [["A", "12:00:00.001", 101, 202, 303]])
        with self.assertRaisesRegex(ValueError, "absolute tracker"):
            read_offsets(self.path, "A")
        self.assertEqual(read_offsets(self.path, "A", (100, 200, 300))[0][0][2], (1, 2, 3))

    def test_nonfinite_fails(self):
        self.csv(DISTANCE_COLUMNS, [["A", "12:00:00.001", "nan", 0, 0]])
        with self.assertRaises(ValueError):
            read_offsets(self.path, "A")

    def test_recorder_to_importer(self):
        sys.path.insert(0, str(ROOT.parent))
        from base_gui import PullbackRecorder
        recorder = PullbackRecorder(str(self.directory), 10)
        path = recorder.start()
        recorder.write_frame({"RX1": (1, 2, 3), "RX2": (1, 2, -7)}, "A")
        recorder.stop()
        from pullback_core import read_paths
        self.assertEqual(read_paths(path)[0][2], [[(-1, -2, 13)]])



class PathTests(CoreTests):
    def test_prepared_marker_and_segments_are_preserved(self):
        from pullback_core import read_paths
        self.csv(TRACKER_COLUMNS + ("Path Type", "Segment", "Sample Kind"),
                 [["A", "", -5, -6, 7, "centerline_v1", 1, "modeled"],
                  ["A", "", -7, -6, 10, "centerline_v1", 1, "modeled"],
                  ["A", "", -20, -6, 20, "centerline_v1", 2, "modeled"]])
        path = read_paths(self.path, include_metadata=True)[0]
        self.assertTrue(path[3])
        self.assertEqual(path[2], [[(5, 6, 7), (7, 6, 10)], [(20, 6, 20)]])

    def test_invalid_prepared_files_fail_before_import(self):
        from pullback_core import read_paths
        for rows in (
            [["A", "", 1, 2, 3, "unknown", 1]],
            [["A", "", 1, 2, 3, "centerline_v1", ""]],
            [["A", "", 1, 2, 3, "centerline_v1", 1], ["A", "", 2, 3, 3, "centerline_v1", 1]],
            [["A", "", 1, 2, 3, "centerline_v1", 1], ["A", "", 2, 3, 4, "", 1]],
            [["A", "", 1, 2, 3, "centerline_v1", 1], ["A", "", 2, 3, 4, "centerline_v1", 2],
             ["A", "", 3, 4, 5, "centerline_v1", 1]],
        ):
            self.csv(TRACKER_COLUMNS + ("Path Type", "Segment"), rows)
            with self.assertRaises(ValueError):
                read_paths(self.path)

    def test_absolute_coordinates_take_precedence(self):
        from pullback_core import read_paths
        self.csv(TRACKER_COLUMNS + DISTANCE_COLUMNS,
                 [["A", "1", -10, -20, 30, 999, 999, 999],
                  ["A", "2", -11, -21, 31, 999, 999, 999]])
        paths = read_paths(str(self.path))
        self.assertEqual(paths[0][2], [[(10, 20, 30), (11, 21, 31)]])

    def test_files_needles_and_gaps_stay_separate(self):
        from pullback_core import read_paths
        self.csv(TRACKER_COLUMNS, [["A", "1", 1, 2, 3],
                 ["A", "2", "", "", ""], ["A", "3", 4, 5, 6],
                 ["B", "4", 7, 8, 9]])
        other = self.directory / "other.csv"
        other.write_text(self.path.read_text())
        paths = read_paths(str(self.directory))
        self.assertEqual(len(paths), 4)
        self.assertEqual(len(paths[0][2]), 2)

    def test_distance_only_rejected(self):
        from pullback_core import read_paths
        self.csv(DISTANCE_COLUMNS, [["A", "1", 1, 2, 3]])
        with self.assertRaisesRegex(ValueError, "absolute"):
            read_paths(str(self.path))

    def test_interpolation_and_connectivity(self):
        from pullback_core import interpolate, connected_cells
        points = list(interpolate([(0, 0, 0), (0, 0, 4)], 0.5))
        self.assertEqual(len(points), 9)
        self.assertEqual(points[-1], (0, 0, 4))
        cells = list(connected_cells((0, 0, 0), (2, -1, 1)))
        self.assertEqual(cells[-1], (2, -1, 1))
        for a, b in zip(cells, cells[1:]):
            self.assertEqual(sum(abs(x-y) for x,y in zip(a,b)), 1)


class SmoothCurveTests(unittest.TestCase):
    def test_jitter_suppressed_without_flattening_nonuniform_bends(self):
        from pullback_core import fit_sheath_curve
        import math
        def center(z):
            return (10 + 3 * math.sin(z / 5), 20 + 0.01 * z*z, z)
        points = [(x + dx, y + dy, z) for z in range(31)
                  for x, y, z in [center(z)]
                  for dx, dy in ((0.8, -0.6), (-0.8, 0.6))]
        curve = fit_sheath_curve([points])
        rms = math.sqrt(sum(sum((a-b)**2 for a, b in zip(p, center(p[2])))
                            for p in curve) / len(curve))
        self.assertLess(rms, 0.15)
        self.assertGreater(max(p[0] for p in curve) - min(p[0] for p in curve), 5.5)
        self.assertEqual((curve[0][2], curve[-1][2]), (0, 30))
        self.assertEqual(curve, fit_sheath_curve([list(reversed(points))]))

    def test_gaps_reversals_and_pauses_make_one_full_length_curve(self):
        from pullback_core import fit_sheath_curve
        points = [(10 + 0.2*z, 20 - 0.1*z, z) for z in (0, 1, 2, 6, 7, 10)]
        curve = fit_sheath_curve([points[:3], points[3:] + [points[3]] * 100])
        for x, y, z in curve:
            self.assertAlmostEqual(x, 10 + 0.2*z)
            self.assertAlmostEqual(y, 20 - 0.1*z)
        self.assertEqual((curve[0][2], curve[-1][2]), (0, 10))
        self.assertTrue(any(3 < p[2] < 5 for p in curve))

    def test_same_z_measurements_collapse_to_one_corrected_position(self):
        from pullback_core import fit_sheath_curve
        self.assertEqual(fit_sheath_curve([[(1, 2, 3)] * 3]), [(1, 2, 3)])
        self.assertEqual(fit_sheath_curve([[(1, 2, 3), (3, 4, 3)]]), [(2, 3, 3)])

    def test_global_fit_removes_sparse_jitter_and_isolated_outlier(self):
        from pullback_core import fit_sheath_curve
        import math
        def center(z):
            return (10 + 0.05*z + 2*math.sin(z/25), 20 + 0.02*z + 0.0005*z*z, z)
        points = []
        for index, z in enumerate(range(0, 121, 2)):
            x, y, z = center(z)
            sign = (-1)**index
            points.append((x + 1.5*sign + (20 if z == 58 else 0),
                           y - sign - (18 if z == 58 else 0), z))
        curve = fit_sheath_curve([points[:20], list(reversed(points[20:]))])
        rms = math.sqrt(sum(sum((a-b)**2 for a, b in zip(p, center(p[2])))
                            for p in curve) / len(curve))
        self.assertLess(rms, 0.35)
        self.assertTrue(all(b[2] > a[2] for a, b in zip(curve, curve[1:])))
        self.assertEqual((curve[0][2], curve[-1][2]), (0, 120))
        self.assertGreater(max(p[0] - (10 + 0.05*p[2]) for p in curve), 1.5)
        # A local tracking spike must not cause the centerline to jump sideways.
        for a, b in zip(curve, curve[1:]):
            self.assertLess(math.hypot(b[0]-a[0], b[1]-a[1]), 0.1)

    def test_z_remains_independent_even_when_lateral_noise_has_larger_extent(self):
        from pullback_core import fit_sheath_curve
        points = [(10 + 0.1*z, 20 + 0.2*z, z) for z in range(21)]
        points[10] = (100, -100, 10)
        curve = fit_sheath_curve([points])
        self.assertEqual((curve[0][2], curve[-1][2]), (0, 20))
        self.assertTrue(all(b[2] > a[2] for a, b in zip(curve, curve[1:])))
        for x, y, z in curve:
            self.assertAlmostEqual(x, 10 + 0.1*z, delta=0.05)
            self.assertAlmostEqual(y, 20 + 0.2*z, delta=0.05)

    def test_short_pullback_retains_line_correction(self):
        from pullback_core import fit_sheath_curve
        curve = fit_sheath_curve([[(1, 2, 3), (1.4, 2.3, 3.5)]])
        for actual, expected in zip(curve[0], (1, 2, 3)):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(curve[-1], (1.4, 2.3, 3.5)):
            self.assertAlmostEqual(actual, expected)

    def test_global_curve_has_continuous_slope_and_curvature_at_span_joins(self):
        from pullback_core import fit_sheath_curve
        import math
        points = [(10 + 3*math.sin(z/25), 20 + 0.001*z*z, z) for z in range(101)]
        curve = fit_sheath_curve([points], step_mm=0.01)
        h = curve[1][2] - curve[0][2]
        for z in (20, 40, 60, 80):
            j = next(i for i, p in enumerate(curve) if p[2] == z)
            for axis in (0, 1):
                left_slope = (curve[j][axis]-curve[j-1][axis]) / h
                right_slope = (curve[j+1][axis]-curve[j][axis]) / h
                self.assertAlmostEqual(left_slope, right_slope, delta=0.001)
                left_curvature = (curve[j][axis]-2*curve[j-1][axis]+curve[j-2][axis]) / h**2
                right_curvature = (curve[j+2][axis]-2*curve[j+1][axis]+curve[j][axis]) / h**2
                self.assertAlmostEqual(left_curvature, right_curvature, delta=0.001)

    def test_invalid_curve_parameters_and_empty_path(self):
        from pullback_core import fit_sheath_curve
        with self.assertRaises(ValueError):
            fit_sheath_curve([])
        for value in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                fit_sheath_curve([[(0, 0, 0)]], smoothing_mm=value)
            with self.assertRaises(ValueError):
                fit_sheath_curve([[(0, 0, 0)]], step_mm=value)


class Point:
    def __init__(self):
        self.values = [0, 0, 0]
    def setCoordSystem(self, system):
        raise RuntimeError("Cannot set a new coord system on a noxel point.")
    def setCoord(self, i, value):
        self.values[i] = value
    def toNoxel(self):
        return self
    def toRawDataLocation(self):
        return self
    def getCoord(self, i):
        return int(round(self.values[i]))


class AdapterTests(CoreTests):
    def setUp(self):
        super().setUp()
        support = Path("C:/Program Files/MIM Software/MIM/resources/python/py_support.zip")
        if not support.exists():
            self.skipTest("MIM metadata support not installed")
        sys.path.insert(0, str(support))
        from ext import import_contours
        self.import_contours = import_contours
        self.session, self.image = MagicMock(), MagicMock()
        self.image.getInfo().getModality.return_value = "MR"
        self.image.getSpace().getDimensionCount.return_value = 3
        self.image.getSpace().getDataDims.return_value = [100, 100, 100]
        self.image.createNoxelPointF.side_effect = Point
        self.session.getPointFactory().createPoint.side_effect = lambda space, system, values: Point()
        self.image.getContours.return_value = []
        self.image.getPointOverlays.return_value = []
        self.contour = MagicMock()
        self.contour.isEmpty.return_value = False
        self.contour.getData().getDims.return_value = [100, 100, 100]
        self.contour.getNoxelSizeInMm.return_value = [1, 1, 1]
        self.contour.getSpace().createNoxelPoint.side_effect = Point
        self.contour.getData().createNoxelPointI.side_effect = Point
        self.voxels = set()
        self.contour.getData().setValue.side_effect = lambda p, v: self.voxels.add(tuple(p.values))
        self.image.createNewContour.return_value = self.contour
        self.csv(TRACKER_COLUMNS, [["A", "1", -5, -6, 7], ["A", "2", -5, -6, 10]])

    def test_connected_contour(self):
        result = self.import_contours(self.session, self.image, str(self.path))
        self.assertEqual(result, [self.contour])
        self.assertEqual(self.voxels, {(5, 6, z) for z in range(7, 11)})
        self.contour.sanitize.assert_called_once()
        self.image.createPointContour.assert_not_called()

    def test_prepared_curve_is_not_refitted_and_gaps_are_not_bridged(self):
        from unittest.mock import patch
        self.csv(TRACKER_COLUMNS + ("Path Type", "Segment"),
                 [["A", "", -5, -6, 7, "centerline_v1", 1],
                  ["A", "", -9, -6, 10, "centerline_v1", 1],
                  ["A", "", -20, -6, 20, "centerline_v1", 2]])
        with patch("ext.fit_sheath_curve", side_effect=AssertionError("second fit")):
            result = self.import_contours(self.session, self.image, str(self.path))
        self.assertEqual(result, [self.contour])
        self.assertTrue({(5, 6, 7), (9, 6, 10), (20, 6, 20)} <= self.voxels)
        self.assertFalse(any(10 < z < 20 for x, y, z in self.voxels))

    def test_prepared_out_of_volume_section_is_not_reconnected(self):
        self.csv(TRACKER_COLUMNS + ("Path Type", "Segment"),
                 [["A", "", -5, -6, 7, "centerline_v1", 1],
                  ["A", "", -1000, -6, 8, "centerline_v1", 1],
                  ["A", "", -5, -6, 10, "centerline_v1", 1]])
        self.import_contours(self.session, self.image, str(self.path))
        self.assertEqual(self.voxels, {(5, 6, 7), (5, 6, 10)})

    def test_extension_reload_ignores_cached_old_helper(self):
        import runpy
        import types
        from unittest.mock import patch
        stale = types.ModuleType("pullback_core")
        with patch.dict(sys.modules, {"pullback_core": stale}):
            loaded = runpy.run_path(str(ROOT / "src" / "ext.py"))
            self.assertEqual(loaded["fit_sheath_curve"]([[(1, 2, 3)]]), [(1, 2, 3)])
            result = loaded["import_contours"](self.session, self.image, str(self.path))
        self.assertEqual(result, [self.contour])
        self.assertEqual(self.voxels, {(5, 6, z) for z in range(7, 11)})

    def test_dicom_factory_used_for_image_and_contour_spaces(self):
        self.import_contours(self.session, self.image, str(self.path))
        factory = self.session.getPointFactory()
        self.assertEqual(factory.createPoint.call_count, 2)
        calls = factory.createPoint.call_args_list
        self.assertEqual(calls[0].args, (self.image.getSpace(),
                         factory.getDicomCoordSystem(), [0.0, 0.0, 0.0]))
        self.assertEqual(calls[1].args, (self.contour.getSpace(),
                         factory.getDicomCoordSystem(), [0.0, 0.0, 0.0]))
        self.image.createNoxelPointF.assert_not_called()
        self.contour.getSpace().createNoxelPoint.assert_not_called()

    def test_noisy_samples_make_one_smooth_curved_centerline(self):
        points = [(5 + 0.04*(z-17)**2 + dx, 6 + dy, z)
                  for z in range(7, 28) for dx, dy in ((0.8, -0.6), (-0.8, 0.6))]
        self.csv(TRACKER_COLUMNS,
                 [["A", str(i), -x, -y, z] for i, (x, y, z) in enumerate(points)])
        self.import_contours(self.session, self.image, str(self.path))
        self.assertEqual(self.image.createNewContour.call_count, 1)
        self.assertTrue(all(y == 6 for x, y, z in self.voxels))
        self.assertEqual({z for x, y, z in self.voxels}, set(range(7, 28)))
        self.assertTrue({(9, 6, 7), (5, 6, 17), (9, 6, 27)} <= self.voxels)
        self.assertNotIn((9, 6, 17), self.voxels)
        self.assertNotIn((6, 6, 17), self.voxels)

    def test_curved_sheath_does_not_cut_across_interior(self):
        points = [(5, 6, 7), (7, 6, 12), (12, 6, 20), (9, 6, 28), (5, 6, 33)]
        self.csv(TRACKER_COLUMNS,
                 [["A", str(i), -x, -y, z] for i, (x, y, z) in enumerate(points)])
        self.import_contours(self.session, self.image, str(self.path))
        self.assertTrue({points[0], points[-1]} <= self.voxels)
        self.assertTrue(any(x >= 10 and z == 20 for x, y, z in self.voxels))
        self.assertNotIn((5, 6, 20), self.voxels)
        # Every occupied voxel belongs to the same face-connected path.
        reached, pending = {points[0]}, [points[0]]
        while pending:
            voxel = pending.pop()
            for axis in range(3):
                for direction in (-1, 1):
                    neighbor = list(voxel)
                    neighbor[axis] += direction
                    neighbor = tuple(neighbor)
                    if neighbor in self.voxels and neighbor not in reached:
                        reached.add(neighbor)
                        pending.append(neighbor)
        self.assertEqual(reached, self.voxels)

    def test_recorded_pullback_has_one_connected_spot_per_oblique_axial_slice(self):
        import math
        # Exercise the supplied recording on an oblique, anisotropic MR grid.
        # This checks the cross-sections the user sees, not just 3D connectivity.
        angle = math.radians(21.4)
        class ObliquePoint(Point):
            def getCoord(self, i):
                x, y, z = self.values
                return ((x + 70) / 0.7,
                        (math.cos(angle)*y - math.sin(angle)*z + 80) / 0.7,
                        (math.sin(angle)*y + math.cos(angle)*z + 50) / 1.2)[i]
        self.session.getPointFactory().createPoint.side_effect = lambda *args: ObliquePoint()
        self.image.getSpace().getDataDims.return_value = [300, 300, 300]
        self.contour.getData().getDims.return_value = [300, 300, 300]
        self.contour.getNoxelSizeInMm.return_value = [0.7, 0.7, 1.2]
        source = ROOT.parent / "MIMData" / "09_09_2026_pullback_14_56_31_509638.csv"
        if not source.is_file():
            self.skipTest("Optional local DW02 pullback recording not available")
        result = self.import_contours(self.session, self.image, str(source))
        self.assertEqual(result, [self.contour])
        slices = {}
        for x, y, z in self.voxels:
            slices.setdefault(z, set()).add((x, y))
        self.assertGreater(len(slices), 80)
        self.assertEqual(set(slices), set(range(min(slices), max(slices) + 1)))
        for z, cells in slices.items():
            start = next(iter(cells))
            reached, pending = {start}, [start]
            while pending:
                x, y = pending.pop()
                for neighbor in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                    if neighbor in cells and neighbor not in reached:
                        reached.add(neighbor)
                        pending.append(neighbor)
            self.assertEqual(reached, cells, "Separate contour spots at slice {}".format(z))

    def test_missing_measurement_is_bridged_for_continuous_sheath(self):
        self.csv(TRACKER_COLUMNS, [["A", "1", -5, -6, 7],
                 ["A", "2", "", "", ""], ["A", "3", -5, -6, 12]])
        self.assertEqual(self.import_contours(self.session, self.image, str(self.path)),
                         [self.contour])
        self.assertEqual(self.voxels, {(5, 6, z) for z in range(7, 13)})

    def test_needle_switch_keeps_one_continuous_contour_per_needle(self):
        self.csv(TRACKER_COLUMNS, [["A", "1", -5, -6, 7],
                 ["B", "2", -20, -6, 7], ["A", "3", -5, -6, 12]])
        result = self.import_contours(self.session, self.image, str(self.path))
        self.assertEqual(len(result), 2)
        self.assertEqual(self.voxels, {(5, 6, z) for z in range(7, 13)} | {(20, 6, 7)})

    def test_bounds_before_mutation(self):
        self.csv(TRACKER_COLUMNS, [["A", "1", 1000, 0, 0]])
        self.assertEqual(self.import_contours(self.session, self.image, str(self.path)), [])
        self.image.createNewContour.assert_not_called()
        self.image.createPointContour.assert_not_called()

    def test_outside_point_excluded_but_valid_extent_remains_connected(self):
        self.csv(TRACKER_COLUMNS, [["A", "1", -5, -6, 7],
                 ["A", "2", -1000, -6, 8], ["A", "3", -5, -6, 10]])
        result = self.import_contours(self.session, self.image, str(self.path))
        self.assertEqual(result, [self.contour])
        self.assertEqual(self.voxels, {(5, 6, z) for z in range(7, 11)})
        messages = [c.args[0] for c in self.session.createLogger().info.call_args_list]
        self.assertTrue(any("excluded 1 outside MR" in m for m in messages))

    def test_contour_grid_boundary_is_skipped(self):
        self.contour.getData().getDims.return_value = [100, 100, 9]
        self.import_contours(self.session, self.image, str(self.path))
        self.assertEqual(self.voxels, {(5, 6, 7), (5, 6, 8)})

    def test_failure_rolls_back(self):
        self.contour.getData().setValue.side_effect = RuntimeError("failure")
        with self.assertRaises(RuntimeError):
            self.import_contours(self.session, self.image, str(self.path))
        self.contour.delete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
