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


class SheathFitTests(unittest.TestCase):
    def test_jitter_averaged_and_full_z_extent_preserved(self):
        from pullback_core import fit_sheath_line
        points = [(10 + 0.2*z + dx, 20 - 0.1*z + dy, z)
                  for z in (0, 1.1, 2, 1.9, 5, 10)
                  for dx, dy in ((0.4, -0.3), (-0.4, 0.3))]
        line = fit_sheath_line([points])
        for actual, expected in zip(line, [(10, 20, 0), (12, 19, 10)]):
            for a, e in zip(actual, expected):
                self.assertAlmostEqual(a, e)
        self.assertEqual(line, fit_sheath_line([list(reversed(points))]))

    def test_gaps_joined_and_internal_extrema_used(self):
        from pullback_core import fit_sheath_line
        self.assertEqual(fit_sheath_line([[(2, 3, 5), (2, 3, 10)],
                                        [(2, 3, 0), (2, 3, 4)]]),
                         [(2, 3, 0), (2, 3, 10)])

    def test_single_point_and_no_z_travel(self):
        from pullback_core import fit_sheath_line
        self.assertEqual(fit_sheath_line([[(1, 2, 3)]]), [(1, 2, 3)])
        self.assertEqual(fit_sheath_line([[(1, 2, 3), (3, 4, 3)]]), [(2, 3, 3)])
        with self.assertRaises(ValueError):
            fit_sheath_line([])


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

    def test_extension_reload_ignores_cached_old_helper(self):
        import runpy
        import types
        from unittest.mock import patch
        stale = types.ModuleType("pullback_core")
        with patch.dict(sys.modules, {"pullback_core": stale}):
            loaded = runpy.run_path(str(ROOT / "src" / "ext.py"))
            self.assertEqual(loaded["fit_sheath_line"]([[(1, 2, 3)]]), [(1, 2, 3)])
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

    def test_jitter_and_missing_measurement_make_one_uniform_line(self):
        self.csv(TRACKER_COLUMNS, [["A", "1", -5.4, -5.6, 10],
                 ["A", "2", -4.6, -6.4, 10], ["A", "3", "", "", ""],
                 ["A", "4", -5.4, -5.6, 7], ["A", "5", -4.6, -6.4, 7]])
        self.import_contours(self.session, self.image, str(self.path))
        self.assertEqual(self.voxels, {(5, 6, z) for z in range(7, 11)})

    def test_bounds_before_mutation(self):
        self.csv(TRACKER_COLUMNS, [["A", "1", 1000, 0, 0]])
        self.assertEqual(self.import_contours(self.session, self.image, str(self.path)), [])
        self.image.createNewContour.assert_not_called()

    def test_outside_point_excluded_but_sheath_remains_connected(self):
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
