import csv
import io
import unittest
from datetime import datetime
from unittest.mock import patch

from base_gui import CoilCoordinateLogger


class CoilCoordinateLoggerTests(unittest.TestCase):
    def test_writes_grouped_xyz_coordinates_with_milliseconds(self):
        stream = io.StringIO()
        with patch("builtins.open", return_value=stream):
            logger = CoilCoordinateLogger("coils.csv")
            logger.write(
                {
                    "RX1": {
                        "sagittal": 1.23456,
                        "coronal": 2.34567,
                        "transversal": 3.45678,
                    },
                    "RX2": {
                        "sagittal": 4.56789,
                        "coronal": 5.67891,
                        "transversal": 6.78912,
                    },
                },
                datetime(2026, 8, 20, 11, 40, 50, 500000),
            )
            stream.seek(0)
            rows = list(csv.reader(stream))
            logger.close()

        self.assertEqual(
            rows,
            [
                [
                    "Time              ",
                    "RX1 X (mm)        ",
                    "RX1 Y (mm)        ",
                    "RX1 Z (mm)        ",
                    "RX2 X (mm)        ",
                    "RX2 Y (mm)        ",
                    "RX2 Z (mm)",
                ],
                [
                    "11:40:50.500      ",
                    "1.235             ",
                    "2.346             ",
                    "3.457             ",
                    "4.568             ",
                    "5.679             ",
                    "6.789",
                ],
            ],
        )

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
