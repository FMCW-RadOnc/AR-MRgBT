import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import base_gui


class FakePullbackRecorder:
    def __init__(self):
        self.is_recording = False
        self.points = []

    def start(self):
        self.is_recording = True

    def write_frame(self, coil_measurements, needle_name):
        if self.is_recording:
            self.points.append((needle_name, coil_measurements.copy()))

    def stop(self):
        self.is_recording = False


class PullbackUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        coil_logger_patch = patch("base_gui.CoilCoordinateLogger")
        desired_patch = patch("base_gui.update_desired")
        self.addCleanup(coil_logger_patch.stop)
        self.addCleanup(desired_patch.stop)
        coil_logger_patch.start().return_value = MagicMock()
        desired_patch.start()
        self.window = base_gui.TrackingGUIWindow()
        self.window.pullback_recorder = FakePullbackRecorder()
        self.window.set_desired({
            "Needle A": {
                "transversal": 0.0,
                "coronal": 0.0,
                "sagittal": 0.0,
            },
            "Needle B": {
                "transversal": 0.0,
                "coronal": 0.0,
                "sagittal": 0.0,
            },
        })

    def tearDown(self):
        self.window.display_timer.stop()
        self.window.timer.stop()
        self.window.close()

    def test_button_toggles_recording_and_label(self):
        self.assertEqual(self.window.pullback_button.text(), "Start Pullback")

        self.window.pullback_button.click()

        self.assertTrue(self.window.pullback_recorder.is_recording)
        self.assertEqual(self.window.pullback_button.text(), "Stop Pullback")

        self.window.pullback_button.click()

        self.assertFalse(self.window.pullback_recorder.is_recording)
        self.assertEqual(self.window.pullback_button.text(), "Start Pullback")

    def test_active_pullback_captures_each_tracking_frame(self):
        self.window.pullback_button.click()

        self.window.update_tracking_frame({
            "RX1": (1.0, 2.0, 3.0),
            "RX2": (1.0, 2.0, -7.0),
        })
        self.window.target_combobox.setCurrentText("Needle B")
        self.window.update_tracking_frame({
            "RX1": (1.0, 2.0, 2.0),
            "RX2": (1.0, 2.0, -8.0),
        })

        self.assertEqual(len(self.window.pullback_recorder.points), 2)
        self.assertEqual(
            [point[0] for point in self.window.pullback_recorder.points],
            ["Needle A", "Needle B"],
        )


if __name__ == "__main__":
    unittest.main()
