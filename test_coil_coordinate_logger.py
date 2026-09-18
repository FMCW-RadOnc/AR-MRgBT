import csv
import io
import unittest
from datetime import datetime
from unittest.mock import patch

from base_gui import CoilCoordinateLogger


class CoilCoordinateLoggerTests(unittest.TestCase):
    def test_writes_signed_tip_offsets_with_milliseconds(self):
        stream = io.StringIO()
        with patch("builtins.open", return_value=stream):
            logger = CoilCoordinateLogger("coils.csv")
            tip = {"sagittal": 12.3456, "coronal": 3.0, "transversal": -8.0}
            target = {"sagittal": 10.0, "coronal": 5.0, "transversal": -8.0}
            logger.write(tip, target, datetime(2026, 8, 20, 11, 40, 50, 500000))
            # A newly selected target changes the offsets for the same tip.
            logger.write(tip, tip, datetime(2026, 8, 20, 11, 40, 51))
            stream.seek(0)
            rows = list(csv.reader(stream))
            logger.close()
        self.assertEqual(rows, [
            ["Time", "Distance to target x (mm)",
             "Distance to target y (mm)", "Distance to target z (mm)"],
            ["11:40:50.500", "2.346", "-2.000", "0.000"],
            ["11:40:51.000", "0.000", "0.000", "0.000"],
        ])

    def test_skips_missing_or_invalid_positions(self):
        stream = io.StringIO()
        point = {"sagittal": 1.0, "coronal": 2.0, "transversal": 3.0}
        with patch("builtins.open", return_value=stream):
            logger = CoilCoordinateLogger("coils.csv")
            logger.write(point, None)
            logger.write(None, point)
            logger.write(dict(point, sagittal=float("nan")), point)
            stream.seek(0)
            self.assertEqual(len(list(csv.reader(stream))), 1)
            logger.close()
            logger.write(point, point)

    def test_opens_in_write_mode_for_a_fresh_session(self):
        stream = io.StringIO()
        with patch("builtins.open", return_value=stream) as open_file:
            logger = CoilCoordinateLogger("coils.csv")
            logger.close()

        open_file.assert_called_once_with(
            "coils.csv", "w", newline="", encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main()
