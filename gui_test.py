import math

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

import base_gui


SCROLL_STEP_MM = 0.5


class InteractiveNeedleController(QObject):
    """Drive the simulated needle with mouse position and wheel depth."""

    def __init__(self, window, status_label):
        super().__init__(window)
        self.window = window
        self.status_label = status_label
        self.depth_mm = 0.0
        self.sagittal_mm = 0.0
        self.coronal_mm = 0.0

    @staticmethod
    def position_to_mm(screen_offset, available_travel):
        if available_travel <= 0 or screen_offset == 0:
            return 0.0
        relative_position = min(abs(screen_offset) / available_travel, 1.0)
        distance_mm = (base_gui.MAX_THRESHOLD + 1) ** relative_position - 1
        return -math.copysign(distance_mm, screen_offset)

    def update_xy(self, global_position):
        target_view = self.window.target_view
        position = target_view.mapFromGlobal(global_position.toPoint())
        center_x = target_view.width() / 2
        center_y = target_view.height() / 2
        available_travel = (
            min(target_view.width(), target_view.height())
            * base_gui.XY_TRAVEL_FRACTION
        )
        self.sagittal_mm = self.position_to_mm(
            position.x() - center_x,
            available_travel,
        )
        self.coronal_mm = self.position_to_mm(
            position.y() - center_y,
            available_travel,
        )

    def emit_position(self):
        # Keeping the coils 10 mm apart on the depth axis makes the
        # extrapolated needle tip land at the requested simulated position.
        self.window.update_tracking_frame({
            "RX1": (
                self.sagittal_mm,
                self.coronal_mm,
                self.depth_mm - 10.0,
            ),
            "RX2": (
                self.sagittal_mm,
                self.coronal_mm,
                self.depth_mm - 20.0,
            ),
        })
        self.status_label.setText(
            "Move mouse: X/Y   |   Scroll: in/out   |   "
            f"Depth: {self.depth_mm:+.1f} mm"
        )

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseMove:
            self.update_xy(event.globalPosition())
            self.emit_position()
        elif event.type() == QEvent.Type.Wheel:
            self.update_xy(event.globalPosition())
            wheel_steps = event.angleDelta().y() / 120.0
            self.depth_mm = max(
                -base_gui.MAX_THRESHOLD,
                min(
                    base_gui.MAX_THRESHOLD,
                    self.depth_mm + wheel_steps * SCROLL_STEP_MM,
                ),
            )
            self.emit_position()
            return True
        return super().eventFilter(watched, event)


if __name__ == "__main__":
    app = QApplication([])

    window = base_gui.TrackingGUIWindow()
    window.set_desired({
        "Test Point": {
            "transversal": 0.0,
            "coronal": 0.0,
            "sagittal": 0.0,
        }
    })

    status_label = QLabel(window)
    status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    status_label.setFont(QFont("Arial", 16))
    status_label.setStyleSheet("background-color: lightblue;")
    label_width = int(window.width() * 0.6)
    status_label.setGeometry(
        int((window.width() - label_width) / 2), 10, label_width, 45
    )
    status_label.show()

    controller = InteractiveNeedleController(window, status_label)
    app.installEventFilter(controller)
    for widget in [window, *window.findChildren(QWidget)]:
        widget.setMouseTracking(True)

    controller.emit_position()
    app.exec()
