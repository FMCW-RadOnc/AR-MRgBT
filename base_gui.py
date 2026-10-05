"""
According to Access-i:



R <-> L (sagittal axis), DICOM x

A <-> P (coronal axis), DICOM y

F <-> H (transversal axis), DICOM z
In other literature, I <-> S


Current Code:

Left is S (up) I (down)

Right is A (up) P (down)

Bottom is R (left) L (right)

- left should have -z
- right should have y
- bottom should have x
"""




import os
from PyQt6.QtWidgets import (
    QWidget,
    QApplication,
    QMainWindow,
    QComboBox,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
)
from PyQt6.QtGui import (
    QColorConstants,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QFont,
    QShortcut,
    QKeySequence,
)
import math
from PyQt6.QtCore import Qt, QTimer, QTime, QPointF, QRectF
import csv
import threading
from kalman_filter import KalmanFilter
from one_euro_filter import OneEuroFilter
from pullback_recorder import PullbackRecorder, PullbackSettings, calculate_tracker_tip
from display_median import DisplayMedianBuffer
from datetime import datetime
import statistics
import json

ROLLING_INTERVAL = None
KF_PROCESS_NOISE_COEF = None
KF_OBSERVATION_NOISE_COEF = None
ONE_EURO_MIN_CUTOFF_HZ = None
ONE_EURO_BETA = None
ONE_EURO_DERIVATIVE_CUTOFF_HZ = None
ONE_EURO_MAX_SPEED_MM_S = None
TARGET_UPDATE_FREQ_MS = None
DISPLAY_UPDATE_FREQ_MS = None
GREEN_THRESHOLD = None
YELLOW_THRESHOLD = None
MAX_THRESHOLD = None
DIST_BETWEEN_RX1_AND_NEEDLE_TIP = None
PULLBACK_SETTINGS = None
XY_TRAVEL_FRACTION = 0.37
COIL_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "coil_coordinates_log.csv",
)
PULLBACK_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "MIMData",
)


class CoilCoordinateLogger:
    """Write signed needle-tip offsets from the selected target per refresh."""

    def __init__(self, path=COIL_LOG_PATH):
        # Each application run starts a fresh log.
        self._file = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow([
            "Time",
            "Distance to target x (mm)",
            "Distance to target y (mm)",
            "Distance to target z (mm)",
        ])
        self._file.flush()

    def write(self, needle_tip, target, timestamp=None):
        if needle_tip is None or target is None or self._file.closed:
            return
        offsets = [
            needle_tip[axis] - target[axis]
            for axis in ("sagittal", "coronal", "transversal")
        ]
        if not all(math.isfinite(value) for value in offsets):
            return
        if timestamp is None:
            timestamp = datetime.now()
        self._writer.writerow([
            timestamp.strftime("%H:%M:%S.%f")[:-3],
            *(f"{value:.3f}" for value in offsets),
        ])
        self._file.flush()

    def close(self):
        if not self._file.closed:
            self._file.close()

def init_params():
    global PULLBACK_SETTINGS, ROLLING_INTERVAL, KF_PROCESS_NOISE_COEF, KF_OBSERVATION_NOISE_COEF, ONE_EURO_MIN_CUTOFF_HZ, ONE_EURO_BETA, ONE_EURO_DERIVATIVE_CUTOFF_HZ, ONE_EURO_MAX_SPEED_MM_S, TARGET_UPDATE_FREQ_MS, DISPLAY_UPDATE_FREQ_MS, GREEN_THRESHOLD, YELLOW_THRESHOLD, MAX_THRESHOLD, DIST_BETWEEN_RX1_AND_NEEDLE_TIP
    with open("params.json", "r") as p:
        par = json.load(p)
    PULLBACK_SETTINGS = PullbackSettings(**par.get("pullback", {}))
    ROLLING_INTERVAL = par["rolling_interval"]
    KF_PROCESS_NOISE_COEF = par["kf_process_noise_coef_mm"]
    KF_OBSERVATION_NOISE_COEF = par["kf_observation_noise_coef_mm"]
    ONE_EURO_MIN_CUTOFF_HZ = par["one_euro_min_cutoff_hz"]
    ONE_EURO_BETA = par["one_euro_beta"]
    ONE_EURO_DERIVATIVE_CUTOFF_HZ = par["one_euro_derivative_cutoff_hz"]
    ONE_EURO_MAX_SPEED_MM_S = par["one_euro_max_speed_mm_s"]
    TARGET_UPDATE_FREQ_MS = par["target_update_freq_ms"]
    DISPLAY_UPDATE_FREQ_MS = par["display_update_freq_ms"]
    GREEN_THRESHOLD = par["green_threshold_mm"]
    YELLOW_THRESHOLD = par["yellow_threshold_mm"]
    MAX_THRESHOLD = par["max_threshold_mm"]
    DIST_BETWEEN_RX1_AND_NEEDLE_TIP = par["dist_between_rx1_and_needle_tip_mm"]

def get_color(desired, actual) -> QColor:
    abs_diff = abs(desired-actual)
    if abs_diff <= GREEN_THRESHOLD:
        return QColorConstants.Green
    elif abs_diff <= YELLOW_THRESHOLD:
        return QColorConstants.Yellow
    else:
        return QColorConstants.Red
    
# Returns a float between -1.0 and 1.0, where 0 is in the center of the axis, -1 is on the bottom/left, and 1 is on the top/right
def get_relative_position(desired, actual):
    abs_diff = abs(desired-actual)
    rp_capped = math.log2(min(abs_diff, MAX_THRESHOLD)+1) / math.log2(MAX_THRESHOLD+1)
    return rp_capped if desired > actual else -rp_capped


def draw_diagonal_hatch(
    painter, left, top, right, bottom, color, line_width=2.5, spacing=7.0
):
    """Draw hatch strokes whose colored and transparent widths are similar."""
    height = max(0.0, bottom - top)
    painter.setPen(QPen(color, line_width))
    start_x = left - height
    while start_x <= right:
        painter.drawLine(
            QPointF(start_x, top), QPointF(start_x + height, bottom)
        )
        start_x += spacing


class AxisBar(QFrame):
    def __init__(self, is_vertical, perspective=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_vertical = is_vertical
        self.perspective = perspective
        self.headset_mode = False
        self.middle_pen = QPen(QColorConstants.DarkMagenta, 8.0)
        self.actual = None
        self.desired = None
        if perspective:
            self.setStyleSheet(
                "background-color: rgba(0, 0, 0, 0); border: none;"
            )
        else:
            self.setStyleSheet(
                "background-color: rgba(0, 0, 0, 0); "
                "border: 2px solid black; border-radius: 5px;"
            )

        self.no_desired_data_label = QLabel(
            "No\nGoal\nPoint\nData" if is_vertical else "No Goal Point Data",
            parent=self,
        )
        self.no_desired_data_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter
            if is_vertical
            else Qt.AlignmentFlag.AlignVCenter
        )
        self.no_desired_data_label.setFont(QFont('Arial', 20))
        self.no_desired_data_label.setStyleSheet(
            "background-color: white; border: none;"
        )
        self.no_desired_data_label.setWordWrap(True)
        self.no_desired_data_label.hide()

        self.no_actual_data_label = QLabel(
            "No\nCoil\nData" if is_vertical else "No Coil Data", parent=self
        )
        self.no_actual_data_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter
            if is_vertical
            else Qt.AlignmentFlag.AlignVCenter
        )
        self.no_actual_data_label.setFont(QFont('Arial', 20))
        self.no_actual_data_label.setStyleSheet(
            "background-color: white; border: none;"
        )
        self.no_actual_data_label.setWordWrap(True)
        self.no_actual_data_label.hide()

        self.data_label = QLabel("", parent=self)
        self.data_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter
            if is_vertical
            else Qt.AlignmentFlag.AlignVCenter
        )
        self.data_label.setFont(QFont('Arial', 15))
        self.data_label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 0); border: none;"
        )
        self.data_label.hide()

        self.update_timer = QTimer(self)
        self.update_timer.setInterval(DISPLAY_UPDATE_FREQ_MS)
        self.update_timer.timeout.connect(self.update)
        self.update_timer.start()

    def set_actual(self, actual):
        self.actual = actual

    def set_desired(self, desired):
        self.desired = desired

    def set_headset_mode(self, enabled):
        self.headset_mode = enabled
        outline_color = "white" if enabled else "black"
        if self.perspective:
            self.setStyleSheet(
                "background-color: rgba(0, 0, 0, 0); border: none;"
            )
        else:
            self.setStyleSheet(
                "background-color: rgba(0, 0, 0, 0); "
                f"border: 2px solid {outline_color}; border-radius: 5px;"
            )

        if enabled:
            missing_data_style = (
                "color: white; background-color: transparent; border: none;"
            )
            data_style = (
                "color: white; background-color: transparent; border: none;"
            )
        else:
            missing_data_style = (
                "color: black; background-color: white; border: none;"
            )
            data_style = (
                "color: black; background-color: transparent; border: none;"
            )
        self.no_desired_data_label.setStyleSheet(missing_data_style)
        self.no_actual_data_label.setStyleSheet(missing_data_style)
        self.data_label.setStyleSheet(data_style)
        self.update()

    def outline_color(self):
        return (
            QColorConstants.White
            if self.headset_mode
            else QColorConstants.Black
        )

    def perspective_path(self):
        path = QPainterPath()
        top_inset = self.width() * 0.36
        top = self.height() * 0.30
        bottom = self.height() * 0.70
        path.moveTo(top_inset, top)
        path.lineTo(self.width() - top_inset, top)
        path.lineTo(self.width(), bottom)
        path.lineTo(0, bottom)
        path.closeSubpath()
        return path

    def draw_perspective_outline(self, painter):
        top = self.height() * 0.30
        middle = self.height() * 0.50
        bottom = self.height() * 0.70
        top_inset = self.width() * 0.36
        middle_inset = top_inset / 2

        upper_path = QPainterPath()
        upper_path.moveTo(middle_inset, middle)
        upper_path.lineTo(top_inset, top)
        upper_path.lineTo(self.width() - top_inset, top)
        upper_path.lineTo(self.width() - middle_inset, middle)

        dashed_pen = QPen(self.outline_color(), 2.0)
        dashed_pen.setStyle(Qt.PenStyle.DashLine)
        dashed_pen.setDashPattern([3.0, 4.5])
        painter.setPen(dashed_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(upper_path)

        lower_path = QPainterPath()
        lower_path.moveTo(middle_inset, middle)
        lower_path.lineTo(0, bottom)
        lower_path.lineTo(self.width(), bottom)
        lower_path.lineTo(self.width() - middle_inset, middle)

        painter.setPen(QPen(self.outline_color(), 2.0))
        painter.drawPath(lower_path)

    def paintEvent(self, _):
        painter = QPainter(self)
        if self.perspective:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            perspective_path = self.perspective_path()
            self.draw_perspective_outline(painter)

        if self.desired is None:
            self.no_actual_data_label.hide()
            self.no_desired_data_label.show()
            self.no_desired_data_label.adjustSize()
            self.data_label.hide()
            return
        if self.actual is None:
            self.no_desired_data_label.hide()
            self.no_actual_data_label.show()
            self.no_actual_data_label.adjustSize()
            self.data_label.hide()
            return

        color = get_color(self.desired, self.actual)
        if self.headset_mode:
            color = QColor(color)
            color.setAlpha(150)
        painter.setPen(color)
        too_far_in = self.perspective and self.actual > self.desired
        painter.setBrush(Qt.BrushStyle.NoBrush if too_far_in else color)

        if self.perspective:
            painter.save()
            painter.setClipPath(perspective_path)

        if self.is_vertical:
            if self.perspective:
                bar_top = self.height() * 0.30
                bar_bottom = self.height() * 0.70
                center = (bar_top + bar_bottom) / 2
                half_length = (bar_bottom - bar_top) / 2
            else:
                center = self.height() / 2
                half_length = center
            actual_position = (
                center
                + get_relative_position(self.desired, self.actual) * half_length
            )
            fill_top = min(center, actual_position)
            fill_height = abs(actual_position - center)
            if too_far_in:
                painter.save()
                painter.setClipRect(
                    QRectF(0, fill_top, self.width(), fill_height),
                    Qt.ClipOperation.IntersectClip,
                )
                draw_diagonal_hatch(
                    painter,
                    0,
                    fill_top,
                    self.width(),
                    fill_top + fill_height,
                    color,
                )
                painter.restore()
            else:
                painter.drawRect(
                    0,
                    int(fill_top),
                    self.width(),
                    int(fill_height),
                )
            painter.setPen(self.middle_pen)
            painter.drawLine(0, int(center), self.width(), int(center))
        else:
            center = self.width() / 2
            actual_position = (
                center + get_relative_position(self.desired, self.actual) * center
            )
            painter.drawRect(
                int(min(center, actual_position)),
                0,
                int(abs(actual_position - center)),
                self.height(),
            )
            painter.setPen(self.middle_pen)
            painter.drawLine(int(center), 0, int(center), self.height())

        if self.perspective:
            painter.restore()
            self.draw_perspective_outline(painter)

        self.data_label.setText(str(round(self.actual - self.desired, 2)))
        self.data_label.adjustSize()
        if self.perspective:
            trapezoid_bottom = self.height() * 0.70
            self.data_label.move(
                4, int(trapezoid_bottom - self.data_label.height() - 4)
            )
        self.data_label.show()
        self.no_actual_data_label.hide()
        self.no_desired_data_label.hide()


class AxisVisual(QWidget):
    def __init__(self, is_vertical, labels, perspective=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.perspective = perspective
        layout = None
        if not perspective:
            layout = QVBoxLayout(self) if is_vertical else QHBoxLayout(self)

        self.axis_label1 = QLabel(labels[0], parent=self)
        self.axis_label1.setFont(QFont('Arial', 30))
        self.axis_label1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if layout is not None:
            layout.addWidget(self.axis_label1, 1)

        self.bar = AxisBar(
            is_vertical=is_vertical, perspective=perspective, parent=self
        )
        if layout is not None:
            layout.addWidget(self.bar, 8)

        self.axis_label2 = QLabel(labels[1], parent=self)
        self.axis_label2.setFont(QFont('Arial', 30))
        self.axis_label2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if layout is not None:
            layout.addWidget(self.axis_label2, 1)

    def resizeEvent(self, event):
        if self.perspective:
            side_margin = 9
            bar_top = int(self.height() * 0.10)
            bar_height = int(self.height() * 0.80)
            self.bar.setGeometry(
                side_margin,
                bar_top,
                max(1, self.width() - side_margin * 2),
                bar_height,
            )

            label_height = 42
            label_gap = 14
            trapezoid_top = bar_top + int(bar_height * 0.30)
            trapezoid_bottom = bar_top + int(bar_height * 0.70)
            self.axis_label1.setGeometry(
                0,
                trapezoid_top - label_height - label_gap,
                self.width(),
                label_height,
            )
            self.axis_label2.setGeometry(
                0,
                trapezoid_bottom + label_gap,
                self.width(),
                label_height,
            )
            self.axis_label1.raise_()
            self.axis_label2.raise_()
        super().resizeEvent(event)

    def set_actual(self, actual):
        self.bar.set_actual(actual)

    def set_desired(self, desired):
        self.bar.set_desired(desired)

    def set_headset_mode(self, enabled):
        label_style = (
            "color: white; background-color: transparent;"
            if enabled
            else "color: black; background-color: transparent;"
        )
        self.axis_label1.setStyleSheet(label_style)
        self.axis_label2.setStyleSheet(label_style)
        self.bar.set_headset_mode(enabled)

class TargetingView(QWidget):
    """Display lateral, vertical, and depth error as two hollow circles."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setStyleSheet("background-color: gray;")
        self.desired = None
        self.actual = None

        self.status_label = QLabel(parent=self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(
            "color: white; background: transparent; font: 24px Arial;"
        )

        self.update_timer = QTimer(self)
        self.update_timer.setInterval(DISPLAY_UPDATE_FREQ_MS)
        self.update_timer.timeout.connect(self.update)
        self.update_timer.start()

    def set_desired(self, desired):
        self.desired = desired
        self.update()

    def set_actual(self, actual):
        self.actual = actual
        self.update()

    def set_headset_mode(self, enabled):
        background = "black" if enabled else "gray"
        self.setStyleSheet(f"background-color: {background};")
        self.update()

    def resizeEvent(self, event):
        self.status_label.setGeometry(self.rect())
        super().resizeEvent(event)

    def paintEvent(self, _):
        if self.desired is None:
            self.status_label.setText("No Goal Point Data")
            self.status_label.show()
            return
        if self.actual is None:
            self.status_label.setText("No Coil Data")
            self.status_label.show()
            return

        self.status_label.hide()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        center_x = self.width() / 2
        center_y = self.height() / 2
        shortest_side = min(self.width(), self.height())
        needle_base_radius = max(4.0, shortest_side * 0.007)
        target_radius = max(5.0, shortest_side * 0.009)
        tolerance_scale = (
            math.log2(GREEN_THRESHOLD + 1) / math.log2(MAX_THRESHOLD + 1)
        )
        xy_travel = shortest_side * XY_TRAVEL_FRACTION
        tolerance_radius = xy_travel * tolerance_scale

        horizontal_error = get_relative_position(
            self.desired["sagittal"], self.actual["sagittal"]
        )
        vertical_error = get_relative_position(
            self.desired["coronal"], self.actual["coronal"]
        )

        depth_difference = abs(
            self.actual["transversal"] - self.desired["transversal"]
        )
        depth_scale = (
            math.log2(min(depth_difference, MAX_THRESHOLD) + 1)
            / math.log2(MAX_THRESHOLD + 1)
        )
        needle_radius = needle_base_radius * (1.0 + 7.0 * depth_scale)

        # A millimeter of lateral error must occupy the same display distance
        # as a millimeter of vertical error in the projected headset view.
        needle_x = center_x + horizontal_error * xy_travel
        needle_y = center_y + vertical_error * xy_travel

        three_dimensional_error = math.sqrt(
            (self.actual["sagittal"] - self.desired["sagittal"]) ** 2
            + (self.actual["coronal"] - self.desired["coronal"]) ** 2
            + (self.actual["transversal"] - self.desired["transversal"]) ** 2
        )

        tolerance_pen = QPen(QColorConstants.Green, 2.0)
        painter.setPen(tolerance_pen)
        painter.drawEllipse(
            QPointF(center_x, center_y), tolerance_radius, tolerance_radius
        )

        target_pen = QPen(QColorConstants.White, 5.0)
        painter.setPen(target_pen)
        painter.drawEllipse(
            QPointF(center_x, center_y), target_radius, target_radius
        )

        needle_color = get_color(0, three_dimensional_error)
        too_far_in = self.actual["transversal"] > self.desired["transversal"]
        needle_pen = QPen(needle_color, 5.0 if too_far_in else 4.0)
        if too_far_in:
            needle_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            needle_pen.setDashPattern([0.1, 2.5])
        painter.setPen(needle_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(
            QPointF(needle_x, needle_y), needle_radius, needle_radius
        )


class TrackingGUIWindow(QMainWindow):
    def __init__(self):
        super(TrackingGUIWindow, self).__init__()
        init_params()
        self.setStyleSheet("background-color: black;")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        self.desired_positions = {}
        self.coil_positions = {"RX1" : None, "RX2" : None}
        self.needle_tip_position = None
        self.display_positions = DisplayMedianBuffer()
        self.coil_logger = CoilCoordinateLogger()
        self.pullback_recorder = PullbackRecorder(
            tip_offset_mm=DIST_BETWEEN_RX1_AND_NEEDLE_TIP, settings=PULLBACK_SETTINGS
        )
        QApplication.instance().aboutToQuit.connect(self.coil_logger.close)
        QApplication.instance().aboutToQuit.connect(lambda: self.stop_pullback(show_summary=False))

        self.filters : dict[str, KalmanFilter] = {}
        self.one_euro_filters : dict[str, OneEuroFilter] = {}
        self.previous_measurements : dict[str, dict[str, list[float]]] = {}

        self.target_view = TargetingView(parent=self)
        self.setCentralWidget(self.target_view)

        self.filter_combobox = QComboBox(parent=self)
        self.filter_combobox.setStyleSheet("background-color: white;")
        self.filter_combobox.setFont(QFont('Arial', 20))
        self.filter_combobox.activated.connect(self.updated_filter)
        self.filter_combobox.addItems(["No Filter", "Rolling Average", "Rolling Median", "One Euro Filter", "Kalman Filter"])
        self.filter_mode = "One Euro Filter"
        self.filter_combobox.setCurrentText(self.filter_mode)
        self.one_euro_filters = {
            coil_name: OneEuroFilter(
                ONE_EURO_MIN_CUTOFF_HZ,
                ONE_EURO_BETA,
                ONE_EURO_DERIVATIVE_CUTOFF_HZ,
                ONE_EURO_MAX_SPEED_MM_S,
            )
            for coil_name in ("RX1", "RX2")
        }

        self.target_combobox = QComboBox(parent=self)
        self.target_combobox.setStyleSheet("background-color: white;")
        self.target_combobox.setFont(QFont('Arial', 20))
        self.target_combobox.activated.connect(self.updated_text)
        self.target_combobox.activated.connect(self.updated_filter)
        self.combobox_needle_set = set()
        self.current_needle = None

        self.digital_clock = QLabel(parent=self)
        self.digital_clock.setStyleSheet("background-color: black; color: white;")
        self.digital_clock.setFont(QFont('Arial', 30))
        self.digital_clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateTime)
        self.timer.start(1000)

        self.exit_label = QLabel("Hit the Escape Key to exit program.", parent=self)
        self.exit_label.setFont(QFont('Arial', 15))
        self.exit_label.setWordWrap(True)
        self.exit_label.setStyleSheet("background-color: lightblue;")

        self.pullback_button = QPushButton("Start Pullback", parent=self)
        self.pullback_button.setFont(QFont('Arial', 20))
        self.pullback_button.setAccessibleName("Pullback control")
        self.pullback_button.clicked.connect(self.toggle_pullback)
        self.pullback_button.setToolTip("Press Tab to start or stop pullback recording")
        self.pullback_shortcut = QShortcut(QKeySequence("Tab"), self)
        self.pullback_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.pullback_shortcut.setAutoRepeat(False)
        self.pullback_shortcut.activated.connect(self.toggle_pullback)
        self._set_pullback_button_state(False)

        self.transversal_axis = AxisVisual(
            is_vertical=True,
            labels=["S", "I"],
            perspective=True,
            parent=self,
        )
        self.sagittal_axis = AxisVisual(
            is_vertical=False, labels=["R", "L"], parent=self
        )
        self.coronal_axis = AxisVisual(
            is_vertical=True, labels=["A", "P"], parent=self
        )

        # Incoming scans continue to be filtered at their native rate. Only
        # the displayed needle position is reduced to one median every window.
        self.display_timer = QTimer(self)
        self.display_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.display_timer.setInterval(DISPLAY_UPDATE_FREQ_MS)
        self.display_timer.timeout.connect(self.update_display_position)
        self.display_timer.start()

        # The headset presentation is now the application's only view. Keep
        # its low-glare styling active while leaving the corner controls shown.
        self.target_view.set_headset_mode(True)
        self.transversal_axis.set_headset_mode(True)
        self.sagittal_axis.set_headset_mode(True)
        self.coronal_axis.set_headset_mode(True)

        update_desired(self)

        # Adjust the window to full screen based on the screen it's running on
        self.adjust_window_to_screen()

        # Show the window after adjustments
        self.show()

    def updateTime(self):
        current_time = QTime.currentTime()
        label_time = current_time.toString('hh:mm:ss')
        self.digital_clock.setText(label_time)

    def _set_pullback_button_state(self, is_active):
        if is_active:
            self.pullback_button.setText("Stop Pullback")
            background_color = "#b71c1c"
        else:
            self.pullback_button.setText("Start Pullback")
            background_color = "#1b5e20"
        self.pullback_button.setStyleSheet(
            "QPushButton {"
            f"background-color: {background_color}; color: white; "
            "border: 2px solid white; border-radius: 8px; padding: 8px;"
            "}"
            "QPushButton:pressed { background-color: #424242; }"
        )

    def toggle_pullback(self):
        if self.pullback_recorder.is_recording:
            self.stop_pullback()
        else:
            self.start_pullback()

    def start_pullback(self):
        if self.pullback_recorder.is_recording:
            return
        try:
            self.pullback_recorder.start()
        except OSError as error:
            QMessageBox.warning(
                self,
                "Unable to Start Pullback",
                f"The pullback file could not be created:\n{error}",
            )
            return
        self._set_pullback_button_state(True)

    def stop_pullback(self, show_summary=True):
        if not self.pullback_recorder.is_recording:
            return
        try:
            self.pullback_recorder.stop()
        except (OSError, ValueError) as error:
            message = f"A cleaned centerline could not be exported:\n{error}"
            if show_summary:
                QMessageBox.warning(self, "Pullback Cleanup Failed", message)
            else:
                print(message)
        finally:
            self._set_pullback_button_state(False)
        result = self.pullback_recorder.cleaned_path or "No valid centerline exported"
        self.pullback_button.setToolTip(f"{result}\nPress Tab to start or stop pullback recording")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            message_box = QMessageBox(self)
            message_box.setWindowTitle("Exit Confirmation")
            message_box.setText("Click \"Ok\" to exit.")
            message_box.setStyleSheet("background-color: lightblue;")
            message_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            message_box.button(QMessageBox.StandardButton.Ok).setStyleSheet("background-color: green;")
            message_box.button(QMessageBox.StandardButton.Cancel).setStyleSheet("background-color: red;")
            message_box_button = message_box.exec()
            if message_box_button == QMessageBox.StandardButton.Ok:
                QApplication.quit()

    def update_s(self):

        # Adjust the window to full screen based on the screen it's running on
        self.adjust_window_to_screen()

        # Show the window after adjustments
        self.show()

    def set_desired(self, desired_positions):
        self.desired_positions = desired_positions
        for item in self.desired_positions:
            if item not in self.combobox_needle_set:
                self.target_combobox.addItem(item)
                self.combobox_needle_set.add(item)
        if self.current_needle is not None:
            self.target_combobox.setCurrentText(self.current_needle)
        self.current_needle = self.target_combobox.currentText()
        desired = self.desired_positions.get(self.current_needle)
        self.target_view.set_desired(desired)
        if desired is None:
            self.transversal_axis.set_desired(None)
            self.sagittal_axis.set_desired(None)
            self.coronal_axis.set_desired(None)
        else:
            self.transversal_axis.set_desired(desired["transversal"])
            self.sagittal_axis.set_desired(desired["sagittal"])
            self.coronal_axis.set_desired(desired["coronal"])

    def update_coil(self,x,y,z,coil_name):
        """Update one coil without publishing a partial tracking frame."""
        if coil_name not in self.coil_positions:
            return
        
        # Convert from x,y,z to DCM TODO
        measurement = {
            "transversal" : z,
            "coronal" : y,
            "sagittal" : x
        }

        if self.filter_mode == "No Filter":
            self.coil_positions[coil_name] = measurement
        elif self.filter_mode == "Rolling Average":
            self.previous_measurements[coil_name]["transversal"].append(measurement["transversal"])
            if len(self.previous_measurements[coil_name]["transversal"]) > ROLLING_INTERVAL:
                self.previous_measurements[coil_name]["transversal"].pop(0)
            self.previous_measurements[coil_name]["coronal"].append(measurement["coronal"])
            if len(self.previous_measurements[coil_name]["coronal"]) > ROLLING_INTERVAL:
                self.previous_measurements[coil_name]["coronal"].pop(0)
            self.previous_measurements[coil_name]["sagittal"].append(measurement["sagittal"])
            if len(self.previous_measurements[coil_name]["sagittal"]) > ROLLING_INTERVAL:
                self.previous_measurements[coil_name]["sagittal"].pop(0)
            self.coil_positions[coil_name] = {
                "transversal" : statistics.mean(self.previous_measurements[coil_name]["transversal"]),
                "coronal" : statistics.mean(self.previous_measurements[coil_name]["coronal"]),
                "sagittal" : statistics.mean(self.previous_measurements[coil_name]["sagittal"])
            }
        elif self.filter_mode == "Rolling Median":
            self.previous_measurements[coil_name]["transversal"].append(measurement["transversal"])
            if len(self.previous_measurements[coil_name]["transversal"]) > ROLLING_INTERVAL:
                self.previous_measurements[coil_name]["transversal"].pop(0)
            self.previous_measurements[coil_name]["coronal"].append(measurement["coronal"])
            if len(self.previous_measurements[coil_name]["coronal"]) > ROLLING_INTERVAL:
                self.previous_measurements[coil_name]["coronal"].pop(0)
            self.previous_measurements[coil_name]["sagittal"].append(measurement["sagittal"])
            if len(self.previous_measurements[coil_name]["sagittal"]) > ROLLING_INTERVAL:
                self.previous_measurements[coil_name]["sagittal"].pop(0)
            self.coil_positions[coil_name] = {
                "transversal" : statistics.median(self.previous_measurements[coil_name]["transversal"]),
                "coronal" : statistics.median(self.previous_measurements[coil_name]["coronal"]),
                "sagittal" : statistics.median(self.previous_measurements[coil_name]["sagittal"])
            }
        elif self.filter_mode == "One Euro Filter":
            self.coil_positions[coil_name] = self.one_euro_filters[coil_name].update(measurement)
        elif self.filter_mode == "Kalman Filter":
            self.filters[coil_name].update(measurement)
            self.coil_positions[coil_name] = self.filters[coil_name].get()

    def update_tracking_frame(self, coil_measurements):
        """Process both coils from one scanner message as a coherent frame."""
        required_coils = {"RX1", "RX2"}
        # The dedicated recorder validates and filters coherent raw frames;
        # incomplete frames are discarded before centerline export.
        self.pullback_recorder.write_frame(
            coil_measurements,
            self.target_combobox.currentText(),
            timestamp=coil_measurements.get("_pullback_timestamp"),
            monotonic_seconds=coil_measurements.get("_pullback_clock"),
        )

        if not required_coils.issubset(coil_measurements):
            return
        raw_tip, _ = calculate_tracker_tip(coil_measurements["RX1"], coil_measurements["RX2"],
                                           DIST_BETWEEN_RX1_AND_NEEDLE_TIP)
        if raw_tip is None:
            return

        for coil_name in ("RX1", "RX2"):
            x, y, z = coil_measurements[coil_name]
            self.update_coil(x, y, z, coil_name)

        needle_tip = self.calculate_needle_tip()
        if needle_tip is not None:
            self.display_positions.add(needle_tip)

    def calculate_needle_tip(self):
        """Estimate the tip from the latest coherent pair of coil positions."""
        rx1 = self.coil_positions["RX1"]
        rx2 = self.coil_positions["RX2"]
        if rx1 is None or rx2 is None:
            return None

        tip, _ = calculate_tracker_tip(
            (rx1["sagittal"], rx1["coronal"], rx1["transversal"]),
            (rx2["sagittal"], rx2["coronal"], rx2["transversal"]),
            DIST_BETWEEN_RX1_AND_NEEDLE_TIP,
        )
        if tip is None:
            return None

        tip_x, tip_y, tip_z = tip
        return {
            "transversal": tip_z,
            "coronal": tip_y,
            "sagittal": tip_x,
        }

    def update_display_position(self):
        """Publish the median of every needle position in the last window."""
        median_position = self.display_positions.take_median()
        if median_position is None:
            return

        self.needle_tip_position = median_position
        self.coil_logger.write(
            median_position,
            self.desired_positions.get(self.target_combobox.currentText()),
        )
        self.target_view.set_actual(median_position)
        self.transversal_axis.set_actual(median_position["transversal"])
        self.sagittal_axis.set_actual(median_position["sagittal"])
        self.coronal_axis.set_actual(median_position["coronal"])

        # Request the paint immediately after publishing the window median.
        self.target_view.update()
        self.transversal_axis.update()
        self.sagittal_axis.update()
        self.coronal_axis.update()

    def updated_text(self, _):
        self.current_needle = self.target_combobox.currentText()
        desired = self.desired_positions.get(self.current_needle)
        self.target_view.set_desired(desired)
        if desired is None:
            self.transversal_axis.set_desired(None)
            self.sagittal_axis.set_desired(None)
            self.coronal_axis.set_desired(None)
        else:
            self.transversal_axis.set_desired(desired["transversal"])
            self.sagittal_axis.set_desired(desired["sagittal"])
            self.coronal_axis.set_desired(desired["coronal"])

    def updated_filter(self, _):
        self.filter_mode = self.filter_combobox.currentText()
        self.display_positions.clear()
        if self.filter_mode == "No Filter":
            pass
        elif self.filter_mode == "Rolling Average" or self.filter_mode == "Rolling Median":
            self.previous_measurements = {}
            self.previous_measurements["RX1"] = {"transversal" : [], "sagittal" : [], "coronal" : []}
            self.previous_measurements["RX2"] = {"transversal" : [], "sagittal" : [], "coronal" : []}
        elif self.filter_mode == "One Euro Filter":
            self.one_euro_filters = {
                coil_name: OneEuroFilter(
                    ONE_EURO_MIN_CUTOFF_HZ,
                    ONE_EURO_BETA,
                    ONE_EURO_DERIVATIVE_CUTOFF_HZ,
                    ONE_EURO_MAX_SPEED_MM_S,
                )
                for coil_name in ("RX1", "RX2")
            }
        elif self.filter_mode == "Kalman Filter":
            self.filters = {}
            self.filters["RX1"] = KalmanFilter(KF_PROCESS_NOISE_COEF,KF_OBSERVATION_NOISE_COEF)
            self.filters["RX2"] = KalmanFilter(KF_PROCESS_NOISE_COEF,KF_OBSERVATION_NOISE_COEF)

    def adjust_window_to_screen(self):
        # Get the screen where the window is displayed
        screen = self.screen()
        if screen is None:
            # If the screen is not available, use the primary screen
            screen = QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.geometry()
            width = geometry.width()
            height = geometry.height()
            margin = 10
            width_no_margin = width - 2*margin
            height_no_margin = height - 2*margin
            corner_height = int(0.1 * height_no_margin)
            corner_width = int(0.15 * width_no_margin)

            self.digital_clock.setGeometry(margin, margin, corner_width, corner_height)
            self.exit_label.setGeometry(width_no_margin + margin - corner_width, margin, corner_width, corner_height)
            pullback_width = int(0.22 * width_no_margin)
            self.pullback_button.setGeometry(
                margin + int((width_no_margin - pullback_width) / 2),
                margin,
                pullback_width,
                corner_height,
            )
            self.target_combobox.setGeometry(margin, height_no_margin + margin - corner_height, corner_width, corner_height)
            self.filter_combobox.setGeometry(width_no_margin + margin - corner_width, height_no_margin + margin - corner_height, corner_width, corner_height)

            self.transversal_axis.setGeometry(
                margin,
                margin + corner_height,
                int(corner_width * 0.70),
                height_no_margin - corner_height * 2,
            )
            self.coronal_axis.setGeometry(
                width_no_margin + margin - int(corner_width / 2),
                margin + corner_height,
                int(corner_width / 2),
                height_no_margin - corner_height * 2,
            )
            self.sagittal_axis.setGeometry(
                margin + corner_width,
                height_no_margin + margin - corner_height,
                width_no_margin - corner_width * 2,
                corner_height,
            )
            self.setGeometry(geometry)
        else:
            print("No screen information available.")

    # Override showEvent to adjust the window after it is shown
    def showEvent(self, event):
        super(TrackingGUIWindow, self).showEvent(event)
        # Adjust the window to the screen geometry
        self.adjust_window_to_screen()

# Should be run frequently through a thread
def update_desired(window : TrackingGUIWindow):
    t = threading.Timer(TARGET_UPDATE_FREQ_MS / 1000, function=update_desired, args=[window])
    t.daemon = True
    t.start()
    today_str = datetime.today().strftime('%m_%d_%Y')
    desired_data_path = os.path.join("MIMData", f"{today_str}_desired.csv") 
    try:
        
        with open(desired_data_path, mode='r', encoding='UTF-8') as file:
            csvFile = csv.reader(file)    
            desired_positions = {}
            labels = []
            for line in csvFile:
                label = line[0]
                transversal = float(line[1])
                coronal = -float(line[3])
                sagittal = -float(line[2])
                desired_positions[label] = {
                    "transversal" : transversal,
                    "coronal" : coronal,
                    "sagittal" : sagittal
                }
                labels.append(label)
            window.set_desired(desired_positions)
    except:
        print("Something went wrong with loading ", desired_data_path)
