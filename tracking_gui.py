import websocket
import ssl
import json
import requests
import threading
import time
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
)
from PyQt6.QtCore import QObject, pyqtSignal
from base_gui import TrackingGUIWindow

# URLs for the tracking service
BASE_URL = "https://10.243.146.24:7787/SRC/v2/product"
WEBSOCKET_URL = "wss://10.243.146.24:7788/SRC"

# For local testing. Comment this out when using the real image service
#BASE_URL = "https://127.0.0.1:7787/SRC/v2/product"
#WEBSOCKET_URL = "wss://127.0.0.1:7788/SRC"

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
        
def move_to_new_monitor(window : QMainWindow, index):
    s = app.screens()[index]
    qr = s.geometry()
    window.move(qr.left(), qr.top())
    window.update_s()

class Communicate(QObject):
    # One signal represents one scanner message so RX1 and RX2 stay paired.
    data_signal = pyqtSignal(object)

def process_tracking_data(data):
    if data is None:
        print("Received NoneType value, skipping processing.")
        return
    
    """
    The previous approach isn't correct. To get data, we should do this:
    1) Get the coil name as before
    2) Get the "X" projection, "Y" projection, and "Z" projection
    3) From each projection, get the appropriate "x", "y", or "z" (other values will be zero and should be ignored)
    """

    received_clock = time.perf_counter()
    received_stamp = datetime.now().astimezone()
    coil_measurements = {}
    for coil in data["coils"]:
        coil_name = coil["name"]
        projections = {}
        projs = coil["projections"]
        for proj in projs:
            projections[proj["name"]] = proj
        if not {"X", "Y", "Z"}.issubset(projections):
            continue
        x_proj = projections["X"]
        y_proj = projections["Y"]
        z_proj = projections["Z"]
        x = x_proj["coordinates"]["dcs"]["centerPosition"]["x"]
        y = y_proj["coordinates"]["dcs"]["centerPosition"]["y"]
        z = z_proj["coordinates"]["dcs"]["centerPosition"]["z"]
        print(x,y,z, coil_name)
        coil_measurements[coil_name] = (x, y, z)
    # Capture receipt timing before Qt queues the frame for the HUD thread.
    coil_measurements["_pullback_clock"] = received_clock
    coil_measurements["_pullback_timestamp"] = received_stamp
    comm.data_signal.emit(coil_measurements)


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
    window = TrackingGUIWindow()

    # Move GUI to the AR glasses. Index will depend on setup
    #move_to_new_monitor(window, 1)

    comm = Communicate()
    comm.data_signal.connect(window.update_tracking_frame)

    session_id = get_session_id()
    if session_id:
        # Connect to WebSocket and start receiving images
        connect_websocket(session_id)

        # Enable WebSocket messages for the image service
        enable_websocket_messages(session_id)

    # Start the Qt event loop
    app.exec()
