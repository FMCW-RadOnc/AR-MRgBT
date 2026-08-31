import csv
import io
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from base_gui import PullbackRecorder, calculate_tracker_tip


class PullbackRecorderTests(unittest.TestCase):
    def test_tip_formula_extrapolates_from_rx1_away_from_rx2(self):
        tip, separation_mm = calculate_tracker_tip(
            (3.0, 4.0, 0.0),
            (0.0, 0.0, 0.0),
            10.0,
        )

        self.assertEqual(separation_mm, 5.0)
        self.assertEqual(tip, (9.0, 12.0, 0.0))

    def test_records_only_timestamp_sample_tip_and_validity(self):
        self.assertEqual(
            PullbackRecorder.HEADER,
            [
                "Timestamp",
                "Sample",
                "Tip X Tracker (mm)",
                "Tip Y Tracker (mm)",
                "Tip Z Tracker (mm)",
                "Tip Calculation Valid",
            ],
        )
        stream = io.StringIO()
        with patch("builtins.open", return_value=stream):
            recorder = PullbackRecorder(os.getcwd(), tip_offset_mm=10.0)
            path = recorder.start(datetime(2026, 8, 28, 14, 5, 6, 123456))

            self.assertTrue(recorder.is_recording)
            self.assertEqual(
                os.path.basename(path),
                "08_28_2026_pullback_14_05_06_123456.csv",
            )

            recorder.write_frame(
                {"RX1": (1.0, 2.0, 3.0), "RX2": (1.0, 2.0, -7.0)},
                datetime(2026, 8, 28, 14, 5, 7, 500000),
            )
            recorder.write_frame(
                {"RX1": (1.0, 2.0, 3.0), "RX2": (1.0, 2.0, -8.0)},
                datetime(2026, 8, 28, 14, 5, 8, 500000),
            )
            self.assertEqual(recorder.point_count, 2)
            stream.seek(0)
            self.assertEqual(
                list(csv.reader(stream)),
                [
                    PullbackRecorder.HEADER,
                    [
                        "2026-08-28T14:05:07.500",
                        "1",
                        "1.000000", "2.000000", "13.000000",
                        "True",
                    ],
                    [
                        "2026-08-28T14:05:08.500",
                        "2",
                        "1.000000", "2.000000", "13.000000",
                        "True",
                    ],
                ],
            )
            stopped_path = recorder.stop()

            self.assertFalse(recorder.is_recording)
            self.assertEqual(stopped_path, path)

    def test_ignores_points_outside_an_active_pullback(self):
        recorder = PullbackRecorder(os.getcwd())

        recorded = recorder.write_frame({
            "RX1": (1.0, 2.0, 3.0),
            "RX2": (1.0, 2.0, -7.0),
        })

        self.assertFalse(recorded)
        self.assertEqual(recorder.point_count, 0)
        self.assertIsNone(recorder.path)

    def test_zero_sensor_separation_is_recorded_as_invalid(self):
        stream = io.StringIO()
        with patch("builtins.open", return_value=stream):
            recorder = PullbackRecorder(os.getcwd())
            recorder.start(datetime(2026, 8, 28, 14, 5, 6))

            recorder.write_frame(
                {"RX1": (1.0, 2.0, 3.0), "RX2": (1.0, 2.0, 3.0)},
                datetime(2026, 8, 28, 14, 5, 7),
            )

            stream.seek(0)
            row = list(csv.reader(stream))[1]
            self.assertEqual(row[2:5], ["", "", ""])
            self.assertEqual(row[5], "False")
            recorder.stop()


if __name__ == "__main__":
    unittest.main()
