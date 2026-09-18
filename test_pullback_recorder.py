import csv
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
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

    def test_records_only_selected_needle_timestamp_and_tracker_tip(self):
        self.assertEqual(
            PullbackRecorder.HEADER,
            [
                "Needle",
                "Timestamp",
                "X Tracker (mm)",
                "Y Tracker (mm)",
                "Z Tracker (mm)",
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
                "Needle A",
                datetime(2026, 8, 28, 14, 5, 7, 500000),
            )
            recorder.write_frame(
                {"RX1": (1.0, 2.0, 3.0), "RX2": (1.0, 2.0, -8.0)},
                "Needle B",
                datetime(2026, 8, 28, 12, 1, 29, 817123,
                         tzinfo=timezone(timedelta(hours=-5))),
            )
            stream.seek(0)
            self.assertEqual(
                list(csv.reader(stream)),
                [
                    PullbackRecorder.HEADER,
                    [
                        "Needle A",
                        "14:05:07.500",
                        "1.000000", "2.000000", "13.000000",
                    ],
                    [
                        "Needle B",
                        "12:01:29.817",
                        "1.000000", "2.000000", "13.000000",
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
        }, "Needle A")

        self.assertFalse(recorded)
        self.assertIsNone(recorder.path)

    def test_zero_sensor_separation_is_recorded_as_invalid(self):
        stream = io.StringIO()
        with patch("builtins.open", return_value=stream):
            recorder = PullbackRecorder(os.getcwd())
            recorder.start(datetime(2026, 8, 28, 14, 5, 6))

            recorder.write_frame(
                {"RX1": (1.0, 2.0, 3.0), "RX2": (1.0, 2.0, 3.0)},
                "Needle A",
                datetime(2026, 8, 28, 14, 5, 7),
            )

            stream.seek(0)
            row = list(csv.reader(stream))[1]
            self.assertEqual(row[2:5], ["", "", ""])
            recorder.stop()


if __name__ == "__main__":
    unittest.main()
