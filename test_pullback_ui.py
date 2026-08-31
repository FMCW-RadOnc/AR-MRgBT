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

    def write_frame(self, coil_measurements):
        if self.is_recording:
            self.points.append(coil_measurements.copy())

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
        self.window.update_tracking_frame({
            "RX1": (1.0, 2.0, 2.0),
            "RX2": (1.0, 2.0, -8.0),
        })

        self.assertEqual(len(self.window.pullback_recorder.points), 2)


if __name__ == "__main__":
    unittest.main()
