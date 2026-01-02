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




from PyQt6.QtWidgets import (
    QWidget,
    QApplication,
    QMainWindow,
    QComboBox,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QFileDialog,
    QMessageBox
)
from PyQt6.QtGui import QColorConstants, QColor,QPainter,QPen,QFont
import math
from PyQt6.QtCore import Qt
import csv
import numpy as np
import threading
from kalman_filter import KalmanFilter

KF_PROCESS_NOISE_COEF = 5
KF_OBSERVATION_NOISE_COEF = 25

# Checks for new targets once every 1000 ms / 1 second
UPDATE_FREQ_MS = 1000
DESIRED_CSV_PATH = "desired.csv"

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

    def set_actual(self, actual):
        self.actual = actual
        self.update()

    def set_desired(self, desired):
        self.desired = desired
        self.update()
    
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
        self.filters["RX1"] = KalmanFilter(5,25)
        self.filters["RX2"] = KalmanFilter(5,25)

        frame = QFrame(self)
        self.setCentralWidget(frame)

        #self.load_button = QPushButton("LOAD", parent=self)
        #bold_font = QFont('Arial', 20)
        #bold_font.setBold(True)
        #self.load_button.setFont(bold_font)
        #self.load_button.clicked.connect(self.load_point_data)
        #self.load_button.setStyleSheet("background-color: blue;")

        self.target_combobox = QComboBox(parent=self)
        self.target_combobox.setStyleSheet("background-color: white;")
        self.target_combobox.setFont(QFont('Arial', 20))
        self.target_combobox.activated.connect(self.updated_text)
        self.combobox_needle_set = set()
        self.current_needle = None
        
        self.left_axis = AxisVisual(is_vertical=True,labels=["S", "I"],parent=self)
        self.right_axis = AxisVisual(is_vertical=True,labels=["A", "P"], parent=self)
        self.bottom_axis = AxisVisual(is_vertical=False,labels=["R", "L"], parent=self)

        self.exit_label = QLabel("Hit the Escape Key to exit program.", parent=self)
        self.exit_label.setFont(QFont('Arial', 15))
        self.exit_label.setWordWrap(True)
        self.exit_label.setStyleSheet("background-color: lightblue;")

        update_desired(self)

        # Adjust the window to full screen based on the screen it's running on
        self.adjust_window_to_screen()

        # Show the window after adjustments
        self.show()

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
            self.left_axis.set_desired(self.desired_positions[self.current_needle][0])
            self.right_axis.set_desired(self.desired_positions[self.current_needle][1])
            self.bottom_axis.set_desired(self.desired_positions[self.current_needle][2])
        else:
            self.left_axis.set_desired(None)
            self.right_axis.set_desired(None)
            self.bottom_axis.set_desired(None)

    def update_coil(self,x,y,z,coil_name):
        if (not coil_name != "RX1") and (not coil_name != "RX2"):
            return
        
        self.filters[coil_name].update(x,y,z)
        self.coil_positions[coil_name] = self.filters[coil_name].get()

        """
        If we have values for both RX1 and RX2, estimate the needle tip position.
        """
        if self.coil_positions["RX1"] is not None and self.coil_positions["RX2"] is not None:
            x_diff = self.coil_positions["RX1"][0] - self.coil_positions["RX2"][0]
            y_diff = self.coil_positions["RX1"][1] - self.coil_positions["RX2"][1]
            z_diff = self.coil_positions["RX1"][2] - self.coil_positions["RX2"][2]
            diff = np.array([x_diff, y_diff, z_diff])
            unit_diff = diff / np.linalg.norm(diff)
            x_needle_tip = self.coil_positions["RX1"][0] + unit_diff[0].item()*DIST_BETWEEN_RX1_AND_NEEDLE_TIP
            y_needle_tip = self.coil_positions["RX1"][1] + unit_diff[1].item()*DIST_BETWEEN_RX1_AND_NEEDLE_TIP
            z_needle_tip = self.coil_positions["RX1"][2] + unit_diff[2].item()*DIST_BETWEEN_RX1_AND_NEEDLE_TIP
            self.needle_tip_position = (x_needle_tip, y_needle_tip, z_needle_tip)
            self.left_axis.set_actual(-z_needle_tip)
            self.right_axis.set_actual(y_needle_tip)
            self.bottom_axis.set_actual(x_needle_tip)

    def updated_text(self, _):
        self.current_needle = self.target_combobox.currentText()
        if self.current_needle in self.desired_positions:
            self.left_axis.set_desired(self.desired_positions[self.current_needle][0])
            self.right_axis.set_desired(self.desired_positions[self.current_needle][1])
            self.bottom_axis.set_desired(self.desired_positions[self.current_needle][2])
        else:
            self.left_axis.set_desired(None)
            self.right_axis.set_desired(None)
            self.bottom_axis.set_desired(None)

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

            # TODO: Calculate axis dimensions and use those for each axis. 
            d1 = int(min(width_no_margin, height_no_margin) * 0.8)
            d2 = int(min(width_no_margin, height_no_margin) * 0.1)

            # Proportions for the top row widths
            left_margin_proportion = 0.1
            exit_label_proportion = 0.2
            combobox_proportion = 0.4
            load_button_proportion = 0.2
            # Rest is right margin = 0.1

            # Proportion for top row height
            top_row_height = int(0.1 * height_no_margin)

            left_margin_size = int(left_margin_proportion * width_no_margin)
            exit_label_size = int(exit_label_proportion * width_no_margin)
            combobox_size = int(combobox_proportion * width_no_margin)
            load_button_size = int(load_button_proportion * width_no_margin)
            
            self.exit_label.setGeometry(margin + left_margin_size, margin, exit_label_size, top_row_height)
            self.target_combobox.setGeometry(margin + left_margin_size + exit_label_size, margin, combobox_size, top_row_height)
            #self.load_button.setGeometry(margin + left_margin_size + exit_label_size + combobox_size, margin, load_button_size, top_row_height)

            self.left_axis.setGeometry(margin, margin + top_row_height, d2, d1)
            self.right_axis.setGeometry(width_no_margin - d2 - margin, margin + top_row_height, d2, d1)
            self.bottom_axis.setGeometry(margin + int((width_no_margin - d1) / 2), height_no_margin - d2 - margin, d1, d2)
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
    t = threading.Timer(UPDATE_FREQ_MS / 1000, function=update_desired, args=[window])
    t.daemon = True
    t.start()
    try:
        with open(DESIRED_CSV_PATH, mode='r', encoding='UTF-8') as file:
            csvFile = csv.reader(file)    
            desired_positions = {}
            labels = []
            for line in csvFile:
                label = line[0]
                x = float(line[1])
                y = float(line[2])
                z = float(line[3])
                desired_positions[label] = (x,y,z)
                labels.append(label)
            window.set_desired(desired_positions)
    except:
        print("Something went wrong with loading ", DESIRED_CSV_PATH)