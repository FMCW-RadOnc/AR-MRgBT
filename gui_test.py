from PyQt6.QtWidgets import (
    QWidget,
    QApplication,
    QMainWindow,
    QComboBox,
    QGridLayout,
    QFrame
)
from PyQt6.QtGui import QPainter, QColor, QColorConstants, QPen, QFont
from PyQt6.QtCore import Qt

# Maximum difference in mm allowed for a particular color to show on a given axis
GREEN_THRESHOLD = 2
YELLOW_THRESHOLD = 10

coil_names = ["coil1", "coil2", "coil3"]

# Test data
coil_positions = {
    "coil1" : (0,-1,15),
    "coil2" : (2,5,23),
    "coil3" : (100,0,0)
}

desired_positions = {
    "coil1" : (0,0,0),
    "coil2" : (3,4,20),
    "coil3" : (90, 10, 15)
}



max_diff = 30 # Measurement differences are capped at this value in either direction

def get_color(desired, actual) -> QColor:
    abs_diff = abs(desired-actual)
    if abs_diff <= GREEN_THRESHOLD:
        return QColorConstants.Green
    elif abs_diff <= YELLOW_THRESHOLD:
        return QColorConstants.Yellow
    else:
        return QColorConstants.Red

class AxisVisual(QWidget):
    def __init__(self, is_vertical, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_vertical = is_vertical
        self.background_pen = QPen(QColorConstants.Black,1.0)
        self.foreground_pen = QPen(QColorConstants.DarkBlue,5.0)
        self.actual = 0
        self.desired = 0

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

        painter.setPen(self.foreground_pen)
        painter.setBrush(get_color(self.desired, self.actual))

        if self.is_vertical:
            center_y = self.height() / 2
            actual_pos_y = center_y + max(min(self.desired-self.actual, max_diff), -max_diff) / max_diff * center_y
            if center_y < actual_pos_y:
                painter.drawRect(0,int(center_y),self.width(), int(actual_pos_y-center_y))
            else:
                painter.drawRect(0,int(actual_pos_y),self.width(), int(center_y-actual_pos_y))
        else:
            center_x = self.width() / 2
            actual_pos_x = center_x + max(min(self.desired-self.actual, max_diff), -max_diff) / max_diff * center_x
            if center_x < actual_pos_x:
                painter.drawRect(int(center_x),0,int(actual_pos_x-center_x), self.height())
            else:
                painter.drawRect(int(actual_pos_x),0,int(center_x-actual_pos_x), self.height())


class CustomMainWindow(QMainWindow):
    def __init__(self):
        super(CustomMainWindow, self).__init__()
        
        # Make the window transparent
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        # Pens used for painting the rectangles
        self.background_pen = QPen(QColorConstants.Black,1.0)
        self.foreground_pen = QPen(QColorConstants.DarkBlue,5.0)

        layout = QGridLayout()
        frame = QFrame(self)
        frame.setLayout(layout)
        self.setCentralWidget(frame)

        self.coil_combobox = QComboBox()
        self.coil_combobox.addItems(coil_names)
        self.coil_combobox.setFont(QFont('Arial', 20))
        self.coil_combobox.activated.connect(self.current_text)
        self.current_coil = coil_names[0]
        

        self.left_axis = AxisVisual(is_vertical=True)
        self.right_axis = AxisVisual(is_vertical=True)
        self.bottom_axis = AxisVisual(is_vertical=False)

        layout.addWidget(self.coil_combobox,0,1,1,19)
        layout.addWidget(self.bottom_axis,20,1,1,19)
        layout.addWidget(self.left_axis,1,0,19,1)
        layout.addWidget(self.right_axis,1,20,19,1)
        

        self.update_axes()

        # Adjust the window to full screen based on the screen it's running on
        self.adjust_window_to_screen()

        # Show the window after adjustments
        self.show()

    def update_axes(self):
        self.current_coil = self.coil_combobox.currentText()
        self.left_axis.set_actual(coil_positions[self.current_coil][0])
        self.right_axis.set_actual(coil_positions[self.current_coil][1])
        self.bottom_axis.set_actual(coil_positions[self.current_coil][2])
        self.left_axis.set_desired(desired_positions[self.current_coil][0])
        self.right_axis.set_desired(desired_positions[self.current_coil][1])
        self.bottom_axis.set_desired(desired_positions[self.current_coil][2])

    def current_text(self, _):
        self.update_axes()

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

if __name__ == "__main__":
    app = QApplication([])

    # Create the main GUI window
    window = CustomMainWindow()

    # Start the Qt event loop
    app.exec()