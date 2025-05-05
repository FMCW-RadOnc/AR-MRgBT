import websocket
import ssl
import json
import requests
import threading
import base64
import pydicom
from io import BytesIO
import numpy as np
import cv2
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QFrame,
    QGridLayout,
    QLabel,
    QSizePolicy,
)
from PyQt6.QtCore import QObject, pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap, QKeyEvent, QColorConstants, QColor
from queue import Queue
import time


# URLs for the image service
BASE_URL = "https://10.243.146.24:7787/SRC/v2/product"
WEBSOCKET_URL = "wss://10.243.146.24:7788/SRC"

# Global variables for tracking time
last_image_time = None  # Timestamp of the last received image
image_pause_threshold = 5  # Pause threshold in seconds

# Queue to store images for thread-safe updates
image_queue = Queue()

# Global image counter for alternating between left and right
image_counter = 0

# Store original images for adjustments
original_images = {0: None, 1: None}

# Add gamma levels for adjustments
gamma_levels = {0: 1.0, 1: 1.0}  # Default gamma values for left and right images

# Maximum difference in mm allowed for a particular color to show on a given axis
GREEN_THRESHOLD = 2
YELLOW_THRESHOLD = 10

# Dictionary to hold positional data from all coils
coils = {}


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
            "StartDate": "20240909",
            "WarnDate": "20250809",
            "ExpireDate": "20250909",
            "SystemId": "176570",
            "IsReadOptionAvailable": True,
            "IsExecuteOptionAvailable": True,
            "IsAdvancedOptionAvailable": True,
            "Version": "1.0",
            "Hash": "11mgzffmTbH1poO78kgCN7uRgLZUdXW%2BcrTyTucEsEvbTn5qj8DZLU4NMTlhSkUpk%2FmgDHFpWc4IDCEgkV05Kg%3D%3D"
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


# Function to apply gamma correction
def apply_gamma_correction(image, gamma):
    """
    Apply gamma correction to an image.
    Args:
        image (numpy.ndarray): Input image.
        gamma (float): Gamma value (>1 darkens, <1 brightens).
    Returns:
        numpy.ndarray: Gamma-corrected image.
    """
    inv_gamma = 1.0 / gamma
    table = np.array([(i / 255.0) ** inv_gamma * 255 for i in range(256)]).astype("uint8")
    return cv2.LUT(image, table)

# TODO: Add helper function that calculates color given desired and actual position data for an axis
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
        # TODO: Redo GUI
        self.setWindowTitle("Tracking-AR")

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


class Communicate(QObject):
    data_signal = pyqtSignal(np.ndarray, int)

def process_tracking_data(data):
    global coils

    if data is None:
        print("Received NoneType value, skipping processing.")
        return
    
    """
        1) Iterate through <coils> vector
            a) Iterate through <projections> vector
                i) Access positional data in coordinates/dcs
    """
    # TODO: Check how many coils/projections there should typically be and how to use them
    coils = {}
    for coil in data.get("coils"):
        coil_name = coil.get("name")
        projs = {}
        for proj in coil.get("projections"):
            proj_name = proj.get("name")

            # TODO: Confirm whether to use dcs or pcs. Going with pcs for now
            
            orientation = proj.get("coordinates", {}).get("pcs", {}).get("orientation")
            orientation_sag = orientation.get("sag")
            orientation_cor = orientation.get("cor")
            orientation_tra = orientation.get("tra")
            center_position = proj.get("coordinates", {}).get("pcs", {}).get("centerPosition")
            center_position_sag = center_position.get("sag")
            center_position_cor = center_position.get("cor")
            center_position_tra = center_position.get("tra")
            projs[proj_name] = (orientation_sag, orientation_cor, orientation_tra, center_position_sag, center_position_cor, center_position_tra)
        coils[coil_name] = projs

def on_message(ws, message):
    try:
        if isinstance(message, bytes):
            print("Received binary data via WebSocket.")
        else:
            data = json.loads(message)
            service = data.get("service")
            response = data.get("response", {})
            value = response.get("value")
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

    # Create an instance of Communicate for thread-safe signals
    comm = Communicate()
    comm.data_signal.connect(window.update_image)

    session_id = get_session_id()
    if session_id:
        # Connect to WebSocket and start receiving images
        connect_websocket(session_id)

        # Enable WebSocket messages for the image service
        enable_websocket_messages(session_id)

    # Start the Qt event loop
    app.exec()
