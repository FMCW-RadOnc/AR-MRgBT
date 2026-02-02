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
from PyQt6.QtGui import QColorConstants, QColor,QPainter,QPen,QFont
import math
from PyQt6.QtCore import Qt, QTimer, QTime
import csv
import numpy as np
import threading
from kalman_filter import KalmanFilter
from datetime import datetime
import statistics

ROLLING_INTERVAL = 7

KF_PROCESS_NOISE_COEF = 5
KF_OBSERVATION_NOISE_COEF = 25

# Checks for new targets once every 1000 ms / 1 second
TARGET_UPDATE_FREQ_MS = 1000

# Update Axis Bars once every 1000 ms / 1 second
DISPLAY_UPDATE_FREQ_MS = 1000

# Maximum difference in mm allowed for a particular color to show on a given axis
GREEN_THRESHOLD = 2
YELLOW_THRESHOLD = 10
max_diff = 30 # Measurement differences are capped at this value in either direction

DIST_BETWEEN_RX1_AND_NEEDLE_TIP = 10 # Distance in mm between the needle tip and the core nearest to the tip

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
    rp_capped = math.log2(min(abs_diff, max_diff)+1) / math.log2(max_diff+1)
    return rp_capped if desired > actual else -rp_capped

class AxisBar(QFrame):
    def __init__(self, is_vertical, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_vertical = is_vertical
        self.background_pen = QPen(QColorConstants.White,1.0)
        self.middle_pen = QPen(QColorConstants.DarkMagenta, 8.0)
        self.actual = None
        self.desired = None
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0); border: 2px solid black; border-radius: 5px;")
        self.no_desired_data_label = QLabel("No\nGoal\nPoint\nData" if is_vertical else "No Goal Point Data", parent=self)
        self.no_desired_data_label.setAlignment(Qt.AlignmentFlag.AlignHCenter if is_vertical else Qt.AlignmentFlag.AlignVCenter)
        self.no_desired_data_label.setFont(QFont('Arial', 20))
        self.no_desired_data_label.setStyleSheet("background-color: white; border: none;")
        self.no_desired_data_label.setWordWrap(True)
        self.no_desired_data_label.hide()
        self.no_actual_data_label = QLabel("No\nCoil\nData" if is_vertical else "No Coil Data", parent=self)
        self.no_actual_data_label.setAlignment(Qt.AlignmentFlag.AlignHCenter if is_vertical else Qt.AlignmentFlag.AlignVCenter)
        self.no_actual_data_label.setFont(QFont('Arial', 20))
        self.no_actual_data_label.setStyleSheet("background-color: white; border: none;")
        self.no_actual_data_label.setWordWrap(True)
        self.no_actual_data_label.hide()
        self.data_label = QLabel("",parent=self)
        self.data_label.setAlignment(Qt.AlignmentFlag.AlignHCenter if is_vertical else Qt.AlignmentFlag.AlignVCenter)
        self.data_label.setFont(QFont('Arial',15))
        self.data_label.setStyleSheet("background-color: rgba(0, 0, 0, 0); border: none;")
        self.data_label.hide()

        self.update_timer = QTimer(self)
        self.update_timer.setInterval(DISPLAY_UPDATE_FREQ_MS)
        self.update_timer.timeout.connect(self.update)
        self.update_timer.start()


    def set_actual(self, actual):
        self.actual = actual
        #self.update()

    def set_desired(self, desired):
        self.desired = desired
        #self.update()
    
    def paintEvent(self, _):
        painter = QPainter(self)
        #painter.setPen(self.background_pen)
        #painter.setBrush(QColorConstants.White)
        

        #painter.drawRect(0,0,self.width(), self.height())

        if self.desired is None:
            self.no_actual_data_label.hide()
            self.no_desired_data_label.show()
            self.no_desired_data_label.adjustSize()
            self.data_label.hide()
            return
        elif self.actual is None:
            self.no_desired_data_label.hide()
            self.no_actual_data_label.show()
            self.no_actual_data_label.adjustSize()
            self.data_label.hide()
            return
        

        c = get_color(self.desired, self.actual)
        painter.setPen(c)
        painter.setBrush(c)

        if self.is_vertical:
            center_y = self.height() / 2
            actual_pos_y = center_y + get_relative_position(self.desired, self.actual) * center_y
            if center_y < actual_pos_y:
                painter.drawRect(0,int(center_y),self.width(), int(actual_pos_y-center_y))
            else:
                painter.drawRect(0,int(actual_pos_y),self.width(), int(center_y-actual_pos_y))
            painter.setPen(self.middle_pen)
            painter.drawLine(0, int(center_y), self.width(), int(center_y))
        else:
            center_x = self.width() / 2
            actual_pos_x = center_x + get_relative_position(self.desired, self.actual) * center_x
            if center_x < actual_pos_x:
                painter.drawRect(int(center_x),0,int(actual_pos_x-center_x), self.height())
            else:
                painter.drawRect(int(actual_pos_x),0,int(center_x-actual_pos_x), self.height())
            painter.setPen(self.middle_pen)
            painter.drawLine(int(center_x), 0, int(center_x), self.height())
        self.data_label.setText(str(round(self.actual - self.desired, 2)))
        self.data_label.adjustSize()
        self.data_label.show()
        self.no_actual_data_label.hide()
        self.no_desired_data_label.hide()

class AxisVisual(QWidget):
    def __init__(self, is_vertical, labels, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_vertical = is_vertical
        if is_vertical:
            layout = QVBoxLayout(self)
        else:
            layout = QHBoxLayout(self)
        self.axis_label1 = QLabel(labels[0], parent=self)
        self.axis_label1.setFont(QFont('Arial', 30))
        self.axis_label1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.axis_label1.show()
        layout.addWidget(self.axis_label1, 1)

        self.bar = AxisBar(is_vertical=is_vertical, parent=self)

        layout.addWidget(self.bar, 8)

        self.axis_label2 = QLabel(labels[1], parent=self)
        self.axis_label2.setFont(QFont('Arial', 30))
        self.axis_label2.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
        self.axis_label2.show()
        layout.addWidget(self.axis_label2, 1)

    def set_actual(self, actual):
        self.bar.set_actual(actual)

    def set_desired(self, desired):
        self.bar.set_desired(desired)


class TrackingGUIWindow(QMainWindow):
    def __init__(self):
        super(TrackingGUIWindow, self).__init__()
        
        self.setStyleSheet("background-color: gray;")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        self.desired_positions = {}
        self.coil_positions = {"RX1" : None, "RX2" : None}
        self.needle_tip_position = None

        self.filters : dict[str, KalmanFilter] = {}
        self.previous_measurements : dict[str, dict[str, list[float]]] = {}

        frame = QFrame(self)
        self.setCentralWidget(frame)

        self.filter_combobox = QComboBox(parent=self)
        self.filter_combobox.setStyleSheet("background-color: white;")
        self.filter_combobox.setFont(QFont('Arial', 20))
        self.filter_combobox.activated.connect(self.updated_filter)
        self.filter_combobox.addItems(["No Filter", "Rolling Average", "Rolling Median", "Kalman Filter"])
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
        
        self.transversal_axis = AxisVisual(is_vertical=True,labels=["S", "I"],parent=self)
        self.sagittal_axis = AxisVisual(is_vertical=False,labels=["R", "L"], parent=self)
        self.coronal_axis = AxisVisual(is_vertical=True,labels=["A", "P"], parent=self)

        self.exit_label = QLabel("Hit the Escape Key to exit program.", parent=self)
        self.exit_label.setFont(QFont('Arial', 15))
        self.exit_label.setWordWrap(True)
        self.exit_label.setStyleSheet("background-color: lightblue;")

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
        for item in list(self.desired_positions.keys()):
            if item not in self.combobox_needle_set:
                self.target_combobox.addItem(item)
                self.combobox_needle_set.add(item)
        if self.current_needle is not None:
            self.target_combobox.setCurrentText(self.current_needle)
        self.current_needle = self.target_combobox.currentText()
        if self.current_needle in self.desired_positions:
            self.transversal_axis.set_desired(self.desired_positions[self.current_needle]["transversal"])
            self.sagittal_axis.set_desired(self.desired_positions[self.current_needle]["sagittal"])
            self.coronal_axis.set_desired(self.desired_positions[self.current_needle]["coronal"])
        else:
            self.transversal_axis.set_desired(None)
            self.sagittal_axis.set_desired(None)
            self.coronal_axis.set_desired(None)

    def update_coil(self,x,y,z,coil_name):
        if (not coil_name != "RX1") and (not coil_name != "RX2"):
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
        else:
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
            self.transversal_axis.set_actual(transversal_needle_tip)
            self.sagittal_axis.set_actual(sagittal_needle_tip)
            self.coronal_axis.set_actual(coronal_needle_tip)

    def updated_text(self, _):
        self.current_needle = self.target_combobox.currentText()
        if self.current_needle in self.desired_positions:
            self.transversal_axis.set_desired(self.desired_positions[self.current_needle]["transversal"])
            self.sagittal_axis.set_desired(self.desired_positions[self.current_needle]["sagittal"])
            self.coronal_axis.set_desired(self.desired_positions[self.current_needle]["coronal"])
        else:
            self.transversal_axis.set_desired(None)
            self.sagittal_axis.set_desired(None)
            self.coronal_axis.set_desired(None)

    def updated_filter(self, _):
        self.filter_mode = self.filter_combobox.currentText()
        if self.filter_mode == "No Filter":
            pass
        elif self.filter_mode == "Rolling Average" or self.filter_mode == "Rolling Median":
            self.previous_measurements : dict[str, dict[str, list[float]]] = {}
            self.previous_measurements["RX1"] = {"transversal" : [], "sagittal" : [], "coronal" : []}
            self.previous_measurements["RX2"] = {"transversal" : [], "sagittal" : [], "coronal" : []}
        else:
            # Kalman Filter
            self.filters : dict[str, KalmanFilter] = {}
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

            # Proportion for top row height
            corner_height = int(0.1 * height_no_margin)
            corner_width = int(0.15 * width_no_margin)
            
            """
            Clock should be in top left, exit label should be top right,
            current target should be in bottom left (and smaller), current filter should be in bottom right
            """
            self.digital_clock.setGeometry(margin, margin, corner_width, corner_height)
            self.exit_label.setGeometry(width_no_margin + margin - corner_width, margin, corner_width, corner_height)
            self.target_combobox.setGeometry(margin, height_no_margin + margin - corner_height, corner_width, corner_height)
            self.filter_combobox.setGeometry(width_no_margin + margin - corner_width, height_no_margin + margin - corner_height, corner_width, corner_height)
            
            self.transversal_axis.setGeometry(margin, margin + corner_height, int(corner_width / 2), height_no_margin - corner_height*2)
            self.coronal_axis.setGeometry(width_no_margin + margin - int(corner_width / 2), margin + corner_height, int(corner_width / 2), height_no_margin - corner_height*2)
            self.sagittal_axis.setGeometry(margin + corner_width, height_no_margin + margin - corner_height, width_no_margin - corner_width*2, corner_height)
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