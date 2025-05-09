from PyQt6.QtWidgets import (
    QWidget,
    QApplication,
    QMainWindow,
    QComboBox,
    QGridLayout,
    QVBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QFileDialog
)
from PyQt6.QtGui import QPainter, QColor, QColorConstants, QPen, QFont
from PyQt6.QtCore import Qt

import csv
import math

# Maximum difference in mm allowed for a particular color to show on a given axis
GREEN_THRESHOLD = 2
YELLOW_THRESHOLD = 10



# Test data
needle_positions = {
    "Needle 1" : (0,-1,15),
    #"Needle 4" : (2,5,23)
}

needle_names = ["Needle 1", "Needle 4"]





max_diff = 30 # Measurement differences are capped at this value in either direction. Changing this value affects the strength of the logarithm

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

class AxisVisual(QWidget):
    def __init__(self, is_vertical, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_vertical = is_vertical
        self.background_pen = QPen(QColorConstants.White,1.0)
        self.middle_pen = QPen(QColorConstants.DarkMagenta, 8.0)
        self.actual = None
        self.desired = None
        self.desired_positions = {}
        layout = QVBoxLayout(self)
        self.no_desired_data_label = QLabel("No Goal Point Data")
        self.no_desired_data_label.setFont(QFont('Arial', 20))
        self.no_desired_data_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.no_desired_data_label.setStyleSheet("background-color: white;")
        self.no_desired_data_label.hide()
        layout.addWidget(self.no_desired_data_label)
        self.no_actual_data_label = QLabel("No Coil Data")
        self.no_actual_data_label.setFont(QFont('Arial', 20))
        self.no_actual_data_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.no_actual_data_label.setStyleSheet("background-color: white;")
        self.no_actual_data_label.hide()
        layout.addWidget(self.no_actual_data_label)

    def set_actual(self, actual):
        self.actual = actual
        self.update()

    def set_desired(self, desired):
        self.desired = desired
        self.update()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setPen(self.background_pen)
        painter.setBrush(QColorConstants.White)
        painter.drawRect(0,0,self.width(), self.height())

        if self.desired is None:
            self.no_actual_data_label.hide()
            self.no_desired_data_label.show()
            return
        elif self.actual is None:
            self.no_desired_data_label.hide()
            self.no_actual_data_label.show()
            return
        self.no_actual_data_label.hide()
        self.no_desired_data_label.hide()

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


class CustomMainWindow(QMainWindow):
    def __init__(self):
        super(CustomMainWindow, self).__init__()
        
        # Make the window transparent
        #self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background-color: gray;")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        layout = QGridLayout()
        frame = QFrame(self)
        frame.setLayout(layout)
        self.setCentralWidget(frame)

        self.load_button = QPushButton("LOAD", parent=self)
        bold_font = QFont('Arial', 20)
        bold_font.setBold(True)
        self.load_button.setFont(bold_font)
        self.load_button.clicked.connect(self.load_point_data)
        self.load_button.setStyleSheet("background-color: blue;")

        self.needle_combobox = QComboBox()
        self.needle_combobox.setStyleSheet("background-color: white;")
        self.needle_combobox.addItems(needle_names)
        self.needle_combobox.setFont(QFont('Arial', 20))
        self.needle_combobox.activated.connect(self.current_text)
        #self.current_needle = needle_names[0]
        self.current_needle = None
        

        self.left_axis = AxisVisual(is_vertical=True)
        self.s_label = QLabel("S")
        self.s_label.setFont(QFont('Arial', 30))
        self.s_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.i_label = QLabel("I")
        self.i_label.setFont(QFont('Arial', 30))
        self.i_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        

        self.right_axis = AxisVisual(is_vertical=True)
        self.a_label = QLabel("A")
        self.a_label.setFont(QFont('Arial', 30))
        self.a_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.p_label = QLabel("P")
        self.p_label.setFont(QFont('Arial', 30))
        self.p_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.bottom_axis = AxisVisual(is_vertical=False)
        self.r_label = QLabel("R")
        self.r_label.setFont(QFont('Arial', 30))
        self.r_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.l_label = QLabel("L")
        self.l_label.setFont(QFont('Arial', 30))
        self.l_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        layout.addWidget(self.needle_combobox,0,1,1,17)

        layout.addWidget(self.load_button,0,18,1,2)

        layout.addWidget(self.bottom_axis,20,2,1,17)
        layout.addWidget(self.r_label,20,1)
        layout.addWidget(self.l_label,20,19)

        layout.addWidget(self.left_axis,2,0,17,1)
        layout.addWidget(self.s_label,1,0)
        layout.addWidget(self.i_label,19,0)

        layout.addWidget(self.right_axis,2,20,17,1) 
        layout.addWidget(self.a_label,1,20)
        layout.addWidget(self.p_label,19,20)

        

        self.update_axes()

        # Adjust the window to full screen based on the screen it's running on
        self.adjust_window_to_screen()

        # Show the window after adjustments
        self.show()

    def load_point_data(self):
        """
        1) Prompt user to select a CSV file
        2) Load CSV file into desired data
        """
        file_name, _ = QFileDialog.getOpenFileName(self, 'Open Label File', r"<Default dir>", "Label files (*.csv)")
        try:
            with open(file_name, mode='r', encoding='UTF-8') as file:
                csvFile = csv.reader(file)
                try:
                    self.desired_positions = {}
                    for line in csvFile:
                        label = line[0]
                        x = float(line[1])
                        y = float(line[2])
                        z = float(line[3])
                        self.desired_positions[label] = (x,y,z)
                except:
                    print("Something went wrong with loading ", file_name)
                    self.desired_positions = {}
        except:
            print("No valid file selected")
        self.update_axes()

    def update_axes(self):
        self.current_needle = self.needle_combobox.currentText()
        if self.current_needle in needle_positions:
            self.left_axis.set_actual(needle_positions[self.current_needle][0])
            self.right_axis.set_actual(needle_positions[self.current_needle][1])
            self.bottom_axis.set_actual(needle_positions[self.current_needle][2])
        else:
            self.left_axis.set_actual(None)
            self.right_axis.set_actual(None)
            self.bottom_axis.set_actual(None)

        if self.current_needle in self.desired_positions:
            self.left_axis.set_desired(self.desired_positions[self.current_needle][0])
            self.right_axis.set_desired(self.desired_positions[self.current_needle][1])
            self.bottom_axis.set_desired(self.desired_positions[self.current_needle][2])
        else:
            self.left_axis.set_desired(None)
            self.right_axis.set_desired(None)
            self.bottom_axis.set_desired(None)

    def current_text(self, _):
        self.update_axes()

    def update_s(self):
        self.update_axes()

        # Adjust the window to full screen based on the screen it's running on
        self.adjust_window_to_screen()

        # Show the window after adjustments
        self.show()

    def adjust_window_to_screen(self):
        # Get the screen where the window is displayed
        screen = self.screen()
        if screen is None:
            # If the screen is not available, use the primary screen
            screen = QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.geometry()
            self.setGeometry(geometry)
        else:
            print("No screen information available.")

    # Override showEvent to adjust the window after it is shown
    def showEvent(self, event):
        super(CustomMainWindow, self).showEvent(event)
        # Adjust the window to the screen geometry
        self.adjust_window_to_screen()

def move_to_new_monitor(window : QMainWindow, index):
    s = app.screens()[index]
    qr = s.geometry()
    window.move(qr.left(), qr.top())
    window.update_s()

if __name__ == "__main__":
    app = QApplication([])

    # Create the main GUI window
    window = CustomMainWindow()

    # Move GUI to the AR glasses. Index will depend on setup
    move_to_new_monitor(window, 1)

    # Start the Qt event loop
    app.exec()