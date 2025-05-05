import websocket
import ssl
import json
import requests
import threading
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColorConstants, QColor,QPainter,QPen

# URLs for the image service
BASE_URL = "https://10.243.146.24:7787/SRC/v2/product"
WEBSOCKET_URL = "wss://10.243.146.24:7788/SRC"

# Maximum difference in mm allowed for a particular color to show on a given axis
GREEN_THRESHOLD = 2
YELLOW_THRESHOLD = 10

# Test data (Placeholder, will use data from coils eventually)
desired_positions = 0,0,0
actual_positions = 0,-1,15

max_diff = 30 # Measurement differences are capped at this value in either direction

# Dictionary to hold positional data from all coils
coils = {}

"""
    TODO: Answer these: 
    - In what way are we receiving correction information? 
    - At what rate do we receive position information?
    - Do we use multiple coils and projections per coil or just one? If there's multiple, how is the correction data connected?
    - Are we only concerning ourselves with the center position of the coil or is orientation also relevant?
"""

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

# Helper function that calculates color given desired and actual position data for an axis
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

        # Pens used for painting the rectangles
        self.background_pen = QPen(QColorConstants.Black,1.0)
        self.foreground_pen = QPen(QColorConstants.DarkBlue,5.0)

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

    def paintRect(self,painter : QPainter,x1,x2,y1,y2,desired,actual,is_vertical=True):
        painter.setPen(self.background_pen)
        painter.setBrush(QColorConstants.White)
        painter.drawRect(x1,y1,x2-x1,y2-y1)
        l_color = get_color(desired, actual)
        painter.setPen(self.foreground_pen)
        painter.setBrush(l_color)
        if is_vertical:
            center_y = y1 + (y2-y1) / 2
            actual_pos_y = center_y + max(min(desired-actual, max_diff), -max_diff) / max_diff * (y2-y1) / 2
            painter.drawRect(x1, int(min(center_y, actual_pos_y)), x2-x1, int(max(center_y, actual_pos_y))-int(min(center_y, actual_pos_y)))
        else:
            center_x = x1 + (x2-x1) / 2
            actual_pos_x = center_x - max(min(desired - actual, max_diff), -max_diff) / max_diff * (x2-x1) / 2
            painter.drawRect(int(min(center_x, actual_pos_x)), y1, int(max(center_x, actual_pos_x))-int(min(center_x, actual_pos_x)), y2-y1)

    def paintEvent(self, event):
        painter = QPainter(self)
        
        width, height = self.size().width(), self.size().height()

        tile_w, tile_h = (int(width / 32), int(height / 32))

        # Left rectangle
        l_rect_x1 = tile_w
        l_rect_x2 = tile_w*3
        l_rect_y1 = tile_h
        l_rect_y2 = height - tile_h*3
        self.paintRect(painter,l_rect_x1,l_rect_x2,l_rect_y1,l_rect_y2,desired_positions[0],actual_positions[0])

        # Right rectangle
        r_rect_x1 = width - tile_w*3
        r_rect_x2 = width - tile_w
        r_rect_y1 = tile_h
        r_rect_y2 = height - tile_h*3
        self.paintRect(painter,r_rect_x1,r_rect_x2,r_rect_y1,r_rect_y2,desired_positions[1],actual_positions[1])
        
        # Bottom rectangle
        b_rect_x1 = tile_w*3
        b_rect_x2 = width - tile_w*3
        b_rect_y1 = height - tile_h*3
        b_rect_y2 = height - tile_h
        self.paintRect(painter,b_rect_x1,b_rect_x2,b_rect_y1,b_rect_y2,desired_positions[2],actual_positions[2],is_vertical=False)
        
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

    session_id = get_session_id()
    if session_id:
        # Connect to WebSocket and start receiving images
        connect_websocket(session_id)

        # Enable WebSocket messages for the image service
        enable_websocket_messages(session_id)

    # Start the Qt event loop
    app.exec()
