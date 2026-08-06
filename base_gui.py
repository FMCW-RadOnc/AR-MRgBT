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
    QMessageBox
)
from PyQt6.QtGui import (
    QColorConstants,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QFont,
)
import math
from PyQt6.QtCore import Qt, QTimer, QTime, QPointF, QRectF
import csv
import numpy as np
import threading
from kalman_filter import KalmanFilter
from one_euro_filter import OneEuroFilter
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

def init_params():
    global ROLLING_INTERVAL, KF_PROCESS_NOISE_COEF, KF_OBSERVATION_NOISE_COEF, ONE_EURO_MIN_CUTOFF_HZ, ONE_EURO_BETA, ONE_EURO_DERIVATIVE_CUTOFF_HZ, ONE_EURO_MAX_SPEED_MM_S, TARGET_UPDATE_FREQ_MS, DISPLAY_UPDATE_FREQ_MS, GREEN_THRESHOLD, YELLOW_THRESHOLD, MAX_THRESHOLD, DIST_BETWEEN_RX1_AND_NEEDLE_TIP
    with open("params.json", "r") as p:
        par = json.load(p)
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

        dashed_pen = QPen(QColorConstants.Black, 2.0)
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

        painter.setPen(QPen(QColorConstants.Black, 2.0))
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
        self.data_label.show()
        self.no_actual_data_label.hide()
        self.no_desired_data_label.hide()


class AxisVisual(QWidget):
    def __init__(self, is_vertical, labels, perspective=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        layout = QVBoxLayout(self) if is_vertical else QHBoxLayout(self)

        self.axis_label1 = QLabel(labels[0], parent=self)
        self.axis_label1.setFont(QFont('Arial', 30))
        self.axis_label1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.axis_label1, 1)

        self.bar = AxisBar(
            is_vertical=is_vertical, perspective=perspective, parent=self
        )
        layout.addWidget(self.bar, 8)

        self.axis_label2 = QLabel(labels[1], parent=self)
        self.axis_label2.setFont(QFont('Arial', 30))
        self.axis_label2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.axis_label2, 1)

    def set_actual(self, actual):
        self.bar.set_actual(actual)

    def set_desired(self, desired):
        self.bar.set_desired(desired)

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
        target_radius = max(4.0, shortest_side * 0.007)

        horizontal_error = get_relative_position(
            self.desired["sagittal"], self.actual["sagittal"]
        )
        vertical_error = get_relative_position(
            self.desired["coronal"], self.actual["coronal"]
        )
        needle_x = center_x + horizontal_error * self.width() * 0.35
        needle_y = center_y + vertical_error * self.height() * 0.35

        depth_difference = abs(
            self.actual["transversal"] - self.desired["transversal"]
        )
        depth_scale = (
            math.log2(min(depth_difference, MAX_THRESHOLD) + 1)
            / math.log2(MAX_THRESHOLD + 1)
        )
        needle_radius = target_radius * (1.0 + 4.0 * depth_scale)

        largest_axis_error = max(
            abs(self.actual["sagittal"] - self.desired["sagittal"]),
            abs(self.actual["coronal"] - self.desired["coronal"]),
            depth_difference,
        )

        target_pen = QPen(QColorConstants.White, 2.0)
        painter.setPen(target_pen)
        painter.drawEllipse(
            QPointF(center_x, center_y), target_radius, target_radius
        )

        needle_color = get_color(0, largest_axis_error)
        too_far_in = self.actual["transversal"] > self.desired["transversal"]
        needle_pen = QPen(needle_color, 1.5)
        painter.setPen(needle_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(
            QPointF(needle_x, needle_y), needle_radius, needle_radius
        )
        if too_far_in:
            x_extent = max(4.0, needle_radius * 0.7)
            painter.drawLine(
                QPointF(needle_x - x_extent, needle_y - x_extent),
                QPointF(needle_x + x_extent, needle_y + x_extent),
            )
            painter.drawLine(
                QPointF(needle_x - x_extent, needle_y + x_extent),
                QPointF(needle_x + x_extent, needle_y - x_extent),
            )


class TrackingGUIWindow(QMainWindow):
    def __init__(self):
        super(TrackingGUIWindow, self).__init__()
        init_params()
        self.setStyleSheet("background-color: gray;")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        self.desired_positions = {}
        self.coil_positions = {"RX1" : None, "RX2" : None}
        self.needle_tip_position = None

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
        self.filter_mode = "No Filter"

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

        update_desired(self)

        # Adjust the window to full screen based on the screen it's running on
        self.adjust_window_to_screen()

        # Show the window after adjustments
        self.show()

    def updateTime(self):
        current_time = QTime.currentTime()
        label_time = current_time.toString('hh:mm:ss')
        self.digital_clock.setText(label_time)

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

        

        """
        If we have values for both RX1 and RX2, estimate the needle tip position.
        """
        if self.coil_positions["RX1"] is not None and self.coil_positions["RX2"] is not None:
            transversal_diff = self.coil_positions["RX1"]["transversal"] - self.coil_positions["RX2"]["transversal"]
            coronal_diff = self.coil_positions["RX1"]["coronal"] - self.coil_positions["RX2"]["coronal"]
            sagittal_diff = self.coil_positions["RX1"]["sagittal"] - self.coil_positions["RX2"]["sagittal"]
            diff = np.array([transversal_diff, coronal_diff, sagittal_diff], dtype=float)
            unit_diff = diff / np.linalg.norm(diff)
            transversal_unit_diff, coronal_unit_diff, sagittal_unit_diff = unit_diff.tolist()
            transversal_needle_tip = self.coil_positions["RX1"]["transversal"] + transversal_unit_diff*DIST_BETWEEN_RX1_AND_NEEDLE_TIP
            coronal_needle_tip = self.coil_positions["RX1"]["coronal"] + coronal_unit_diff*DIST_BETWEEN_RX1_AND_NEEDLE_TIP
            sagittal_needle_tip = self.coil_positions["RX1"]["sagittal"] + sagittal_unit_diff*DIST_BETWEEN_RX1_AND_NEEDLE_TIP
            self.needle_tip_position = {
                "transversal" : transversal_needle_tip,
                "coronal" : coronal_needle_tip,
                "sagittal" : sagittal_needle_tip
            }
            self.target_view.set_actual(self.needle_tip_position)
            self.transversal_axis.set_actual(transversal_needle_tip)
            self.sagittal_axis.set_actual(sagittal_needle_tip)
            self.coronal_axis.set_actual(coronal_needle_tip)

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
