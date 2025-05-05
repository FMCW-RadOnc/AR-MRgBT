from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QFrame,
    QGridLayout,
    QLabel,
    QSizePolicy
)
from PyQt6.QtGui import QPainter, QColor, QColorConstants, QPen
from PyQt6.QtCore import Qt

# Maximum difference in mm allowed for a particular color to show on a given axis
GREEN_THRESHOLD = 2
YELLOW_THRESHOLD = 10

# Test data
desired_positions = 0,0,0
actual_positions = 0,-1,15

max_diff = 30 # Measurement differences are capped at this value in either direction

def get_color(desired, actual) -> QColor:
    abs_diff = abs(desired-actual)
    if abs_diff <= GREEN_THRESHOLD:
        return QColorConstants.Green
    elif abs_diff <= YELLOW_THRESHOLD:
        return QColorConstants.Yellow
    else:
        return QColorConstants.Red

class CustomMainWindow(QMainWindow):
    def __init__(self):
        super(CustomMainWindow, self).__init__()
        
        # Make the window transparent
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

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

    def paintEvent(self, event):
        painter = QPainter(self)
        
        width, height = self.size().width(), self.size().height()

        tile_w, tile_h = (int(width / 32), int(height / 32))

        background_pen = QPen(QColorConstants.Black,1.0)
        foreground_pen = QPen(QColorConstants.DarkBlue,5.0)

        """
            Current Approach:
            - 1/32th of the screen margins
            - 1/8th of the screen corners
            - rectangles are 1/16th of the screen wide
            - Middle of rectangles are correct, actual and correct are both blue lines
        """

        # Left rectangle
        l_rect_x1 = tile_w
        l_rect_x2 = tile_w*3
        l_rect_y1 = tile_h
        l_rect_y2 = height - tile_h*3
        painter.setPen(background_pen)
        painter.setBrush(QColorConstants.White)
        painter.drawRect(l_rect_x1,l_rect_y1,l_rect_x2-l_rect_x1,l_rect_y2-l_rect_y1)
        l_color = get_color(desired_positions[0], actual_positions[0])
        painter.setPen(foreground_pen)
        painter.setBrush(l_color)
        l_center_y = l_rect_y1 + (l_rect_y2-l_rect_y1) / 2
        l_actual_pos_y = l_center_y + max(min(desired_positions[0] - actual_positions[0], max_diff), -max_diff) / max_diff * (l_rect_y2-l_rect_y1) / 2
        painter.drawRect(l_rect_x1, int(min(l_center_y, l_actual_pos_y)), l_rect_x2-l_rect_x1, int(max(l_center_y, l_actual_pos_y))-int(min(l_center_y, l_actual_pos_y)))


        # Right rectangle
        r_rect_x1 = width - tile_w*3
        r_rect_x2 = width - tile_w
        r_rect_y1 = tile_h
        r_rect_y2 = height - tile_h*3
        painter.setPen(background_pen)
        painter.setBrush(QColorConstants.White)
        painter.drawRect(r_rect_x1,r_rect_y1,r_rect_x2-r_rect_x1,r_rect_y2-r_rect_y1)
        r_color = get_color(desired_positions[1], actual_positions[1])
        painter.setPen(foreground_pen)
        painter.setBrush(r_color)
        r_center_y = r_rect_y1 + (r_rect_y2-r_rect_y1) / 2
        r_actual_pos_y = r_center_y + max(min(desired_positions[1] - actual_positions[1], max_diff), -max_diff) / max_diff * (r_rect_y2-r_rect_y1) / 2
        painter.drawRect(r_rect_x1, int(min(r_center_y, r_actual_pos_y)), r_rect_x2-r_rect_x1, int(max(r_center_y, r_actual_pos_y))-int(min(r_center_y, r_actual_pos_y)))
        
        # Bottom rectangle
        b_rect_x1 = tile_w*3
        b_rect_x2 = width - tile_w*3
        b_rect_y1 = height - tile_h*3
        b_rect_y2 = height - tile_h
        painter.setPen(background_pen)
        painter.setBrush(QColorConstants.White)
        painter.drawRect(b_rect_x1,b_rect_y1,b_rect_x2-b_rect_x1,b_rect_y2-b_rect_y1)
        b_color = get_color(desired_positions[2], actual_positions[2])
        painter.setPen(foreground_pen)
        painter.setBrush(b_color)
        b_center_x = b_rect_x1 + (b_rect_x2-b_rect_x1) / 2
        b_actual_pos_x = b_center_x - max(min(desired_positions[2] - actual_positions[2], max_diff), -max_diff) / max_diff * (b_rect_x2-b_rect_x1) / 2
        painter.drawRect(int(min(b_center_x, b_actual_pos_x)), b_rect_y1, int(max(b_center_x, b_actual_pos_x))-int(min(b_center_x, b_actual_pos_x)), b_rect_y2-b_rect_y1)

if __name__ == "__main__":
    app = QApplication([])

    # Create the main GUI window
    window = CustomMainWindow()

    # Start the Qt event loop
    app.exec()