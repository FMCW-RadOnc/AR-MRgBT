from datetime import datetime
import websocket
import ssl
import json
import requests
import threading
from PyQt6.QtWidgets import (
    QWidget,
    QApplication,
    QMainWindow,
    QComboBox,
    QVBoxLayout,
    QGridLayout,
    QFrame,
    QLabel,
    QPushButton,
    QFileDialog,
    QMessageBox
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QColorConstants, QColor,QPainter,QPen,QFont

import csv
import math

# URLs for the tracking service
BASE_URL = "https://10.243.146.24:7787/SRC/v2/product"
WEBSOCKET_URL = "wss://10.243.146.24:7788/SRC"

# For local testing. Comment this out when using the real image service
#BASE_URL = "https://127.0.0.1:7787/SRC/v2/product"
#WEBSOCKET_URL = "wss://127.0.0.1:7788/SRC"

WRITE_TO_FILE = True

# Maximum difference in mm allowed for a particular color to show on a given axis
GREEN_THRESHOLD = 2
YELLOW_THRESHOLD = 10


max_diff = 30 # Measurement differences are capped at this value in either direction

# Function to check if the Access-i server is active
def is_server_active():
    url = f"{BASE_URL}/remote/getIsActive"
    try:
        response = requests.get(url, verify=False)
        if response.status_code == 200:
            json_response = response.json()
            is_active = json_response.get("value", False)
            print(f"Server is {'active' if is_active else 'inactive'}.")
            return is_active
        else:
            print(f"Failed to check server status. Status code: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while checking server status: {e}")
        return False

# Function to retrieve sessionId from the Access-i service
def get_session_id():
    auth_url = f"{BASE_URL}/authorization/register"
    # Define the request body with your updated registration information
    request_body = {
        "license": {
            "Name": "MCW",
            "Comment": None,
            "StartDate": "20240910",
            "WarnDate": "20260830",
            "ExpireDate": "20260930",
            "SystemId": "176570",
            "IsReadOptionAvailable": True,
            "IsExecuteOptionAvailable": True,
            "IsAdvancedOptionAvailable": True,
            "Version": "1.0",
            "Hash": "gKEzJrSd1S48prCxwZ%2Bwheju0Tyz67NtLwqe3geWm95BzcOYHFU5V4ThQm%2F%2F0dGdElhMmMKKZX0y7%2BcRF007hg%3D%3D"
        },
        "name": "Test Remote Client"
    }

    try:
        response = requests.post(auth_url, json=request_body, verify=False)
        if response.status_code == 200:
            json_response = response.json()
            session_id = json_response.get("sessionId")
            if session_id:
                print(f"Session ID: {session_id}")
                return session_id
            else:
                print("Session ID not found in the response.")
                return None
        else:
            print(f"Failed to get session ID. Status code: {response.status_code}")
            print(f"Response: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None

# Function to enable WebSocket messages for the image service
def enable_websocket_messages(session_id):
    service = "tracking"
    enable_url = f"{BASE_URL}/{service}/connectServiceToDefaultWebSocket?sessionId={session_id}"
    try:
        response = requests.post(enable_url, verify=False)
        if response.status_code == 200:
            print(f"WebSocket messages enabled for service: {service}")
        else:
            print(
                f"Failed to enable WebSocket messages for service: {service}. Status code: {response.status_code}"
            )
            print(f"Response: {response.text}")
    except requests.exceptions.RequestException as e:
        print(
            f"An error occurred while enabling WebSocket messages for service {service}: {e}"
        )

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
        self.data_label = QLabel("")
        self.data_label.setFont(QFont('Arial',20))
        if is_vertical:
            self.data_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)# | Qt.AlignmentFlag.AlignVCenter)
        else:
            self.data_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)# | Qt.AlignmentFlag.AlignHCenter)
        self.data_label.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
        self.data_label.hide()
        layout.addWidget(self.data_label)

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
            self.data_label.hide()
            return
        elif self.actual is None:
            self.no_desired_data_label.hide()
            self.no_actual_data_label.show()
            self.data_label.hide()
            return
        self.data_label.setText(str(round(self.actual - self.desired, 2)))
        self.data_label.show()
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
        
        self.setStyleSheet("background-color: gray;")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        if WRITE_TO_FILE:
            current_datetime = datetime.now()
            formatted_datetime_string = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
            with open("test_data.txt", 'a') as file:
                file.write("\n" + formatted_datetime_string + "\n")

        self.desired_positions = {}
        self.actual_positions = {}

        layout = QGridLayout()
        layout.setColumnStretch(0,1)
        layout.setColumnStretch(1,1)
        layout.setColumnStretch(2,5)
        layout.setColumnStretch(3,1)
        layout.setColumnStretch(4,1)
        layout.setRowStretch(0,0)
        layout.setRowStretch(1,1)
        layout.setRowStretch(2,0)
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
        self.needle_combobox.setFont(QFont('Arial', 20))
        self.needle_combobox.activated.connect(self.updated_text)
        self.combobox_needle_set = set()
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

        self.exit_label = QLabel("Hit the Escape Key to exit program.")
        self.exit_label.setFont(QFont('Arial', 15))
        self.exit_label.setWordWrap(True)

        layout.addWidget(self.exit_label,0,1)
        layout.addWidget(self.needle_combobox,0,2)

        layout.addWidget(self.load_button,0,3)

        layout.addWidget(self.bottom_axis,2,2)
        layout.addWidget(self.r_label,2,1)
        layout.addWidget(self.l_label,2,3)

        layout.addWidget(self.left_axis,1,0)
        layout.addWidget(self.s_label,0,0)
        layout.addWidget(self.i_label,2,0)

        layout.addWidget(self.right_axis,1,4) 
        layout.addWidget(self.a_label,0,4)
        layout.addWidget(self.p_label,2,4)

        # Adjust the window to full screen based on the screen it's running on
        self.adjust_window_to_screen()

        # Show the window after adjustments
        self.show()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            message_box = QMessageBox(self)
            message_box.setWindowTitle("Exit Confirmation")
            message_box.setText("Click \"Ok\" to exit.")
            message_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            message_box_button = message_box.exec()
            if message_box_button == QMessageBox.StandardButton.Ok:
                QApplication.quit()

    def update_s(self):

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
                    labels = []
                    for line in csvFile:
                        label = line[0]
                        x = float(line[1])
                        y = float(line[2])
                        z = float(line[3])
                        self.desired_positions[label] = (x,y,z)
                        labels.append(label)
                    self.needle_combobox.addItems(labels)
                except:
                    print("Something went wrong with loading ", file_name)
                    self.desired_positions = {}
        except:
            print("No valid file selected")

        self.current_needle = self.needle_combobox.currentText()
        if self.current_needle in self.desired_positions:
            self.left_axis.set_desired(self.desired_positions[self.current_needle][0])
            self.right_axis.set_desired(self.desired_positions[self.current_needle][1])
            self.bottom_axis.set_desired(self.desired_positions[self.current_needle][2])
        else:
            self.left_axis.set_desired(None)
            self.right_axis.set_desired(None)
            self.bottom_axis.set_desired(None)
        if self.current_needle in self.actual_positions:
            self.left_axis.set_actual(self.actual_positions[self.current_needle][0])
            self.right_axis.set_actual(self.actual_positions[self.current_needle][1])
            self.bottom_axis.set_actual(self.actual_positions[self.current_needle][2])
        else:
            self.left_axis.set_actual(None)
            self.right_axis.set_actual(None)
            self.bottom_axis.set_actual(None)

    def update_coil(self,x,y,z,coil_name):
        if WRITE_TO_FILE:
            current_datetime = datetime.now()
            formatted_datetime_string = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
            with open("test_data.txt", 'a') as file:
                file.write(f"{formatted_datetime_string}: x = {x}, y = {y}, z = {z}, coil name = {coil_name}\n")
        self.actual_positions[coil_name] = (x,y,z)
        if self.current_needle == coil_name:
            self.left_axis.set_actual(x)
            self.right_axis.set_actual(y)
            self.bottom_axis.set_actual(z)

    def updated_text(self, _):
        self.current_needle = self.needle_combobox.currentText()
        if self.current_needle in self.desired_positions:
            self.left_axis.set_desired(self.desired_positions[self.current_needle][0])
            self.right_axis.set_desired(self.desired_positions[self.current_needle][1])
            self.bottom_axis.set_desired(self.desired_positions[self.current_needle][2])
        else:
            self.left_axis.set_desired(None)
            self.right_axis.set_desired(None)
            self.bottom_axis.set_desired(None)
        if self.current_needle in self.actual_positions:
            self.left_axis.set_actual(self.actual_positions[self.current_needle][0])
            self.right_axis.set_actual(self.actual_positions[self.current_needle][1])
            self.bottom_axis.set_actual(self.actual_positions[self.current_needle][2])
        else:
            self.left_axis.set_actual(None)
            self.right_axis.set_actual(None)
            self.bottom_axis.set_actual(None)

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

class Communicate(QObject):
    # For simplicity, a signal will just be 3 floats: x,y,z coordinates in dcs
    data_signal = pyqtSignal(float, float, float, str)

def process_tracking_data(data):
    if data is None:
        print("Received NoneType value, skipping processing.")
        return
    
    for coil in data["coils"]:
        coil_name = coil["name"]
        proj = coil["projections"][0] # Only using 1 projection for now
        position = proj["coordinates"]["dcs"]["centerPosition"]
        x = position["x"]
        y = position["y"]
        z = position["z"]
        comm.data_signal.emit(x, y, z, coil_name)


def on_message(ws, message):
    try:
        if isinstance(message, bytes):
            print("Received binary data via WebSocket.")
        else:
            data = json.loads(message)
            service = data["service"]
            response = data["response"]
            value = response["value"]
            if service == "product/tracking":
                print("Received a tracking message via WebSocket")
                process_tracking_data(value)
    except json.JSONDecodeError:
        print(f"Received non-JSON message: {message}")
    except Exception as e:
        print(f"An error occurred in on_message: {e}")
        
def on_error(ws, error):
    print(f"WebSocket error: {error}")

def on_close(ws):
    print("WebSocket connection closed")

def on_open(ws):
    print("WebSocket connection opened")

# Function to connect to WebSocket using the retrieved sessionId
def connect_websocket(session_id):
    url = f"{WEBSOCKET_URL}?sessionId={session_id}"

    ws = websocket.WebSocketApp(
        url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )

    # Run the WebSocket connection in a separate thread
    wst = threading.Thread(
        target=ws.run_forever,
        kwargs={
            "sslopt": {
                "cert_reqs": ssl.CERT_NONE,
                "ssl_version": ssl.PROTOCOL_TLSv1_2,
            }
        },
    )
    wst.daemon = True
    wst.start()

# Main process
if __name__ == "__main__":
    if not is_server_active():
        print("Exiting due to inactive server.")
        exit(1)

    app = QApplication([])

    # Create the main GUI window
    window = CustomMainWindow()

    # Move GUI to the AR glasses. Index will depend on setup
    #move_to_new_monitor(window, 1)

    comm = Communicate()
    comm.data_signal.connect(window.update_coil)

    session_id = get_session_id()
    if session_id:
        # Connect to WebSocket and start receiving images
        connect_websocket(session_id)

        # Enable WebSocket messages for the image service
        enable_websocket_messages(session_id)

    # Start the Qt event loop
    app.exec()