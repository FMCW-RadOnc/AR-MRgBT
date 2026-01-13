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
from PyQt6.QtGui import QImage, QPixmap, QKeyEvent
from queue import Queue
import cv2.dnn_superres
import time
import os

# Disable SSL warnings for self-signed certificates (for development purposes)
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

# URLs for the image service
BASE_URL = "https://10.243.146.24:7787/SRC/v2/product"
WEBSOCKET_URL = "wss://10.243.146.24:7788/SRC"

# directory where DICOMs will be saved
SAVE_DIR = "Saved_DICOMs"
os.makedirs(SAVE_DIR, exist_ok=True)  # create once at startup

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

# ================= NEW: plane + template tracking =================
# Which axis each pane likely shows (auto-filled from DICOM headers)
side_axis = {0: None, 1: None}

# Remember last running template so we can restart it later (auto-captured)
last_template = {"id": None, "label": None}
# ================================================================


# ------------------------- Server/session helpers -------------------------

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
    service = "Image"
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


def apply_super_resolution(image_array):
    # Load the super-resolution model
    sr = cv2.dnn_superres.DnnSuperResImpl_create()
    sr.readModel("ESPCN_x4.pb")  # Replace with your model path
    sr.setModel("espcn", 4)  # Model name and scale factor

    # Apply super-resolution
    image_array = cv2.cvtColor(image_array, cv2.COLOR_GRAY2RGB)
    return sr.upsample(image_array)

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

# ================= NEW: Host Control + Template + Plane helpers ================

def get_hc_state(session_id):
    url = f"{BASE_URL}/hostControl/getState?sessionId={session_id}"
    try:
        r = requests.get(url, verify=False)
        js = r.json() if r.status_code == 200 else {}
        val = js.get("value", {})
        return val
    except Exception as e:
        print("getState error:", e)
        return {}

def request_host_control(session_id):
    """Request HC and always print the reason automatically on failure."""
    url = f"{BASE_URL}/hostControl/requestControl"
    try:
        r = requests.post(url, json={"sessionId": session_id}, verify=False)
        js = r.json() if r.status_code == 200 else {}
        ok = js.get("result", {}).get("success", False)
        reason = js.get("result", {}).get("reason", "")
        if ok:
            print("Host control request OK")
            return True
        else:
            # auto print precise reason from getState too
            state = get_hc_state(session_id)
            print(f"Host control request FAILED — reason: {reason or state.get('cannotRequestControlReason')}")
            return False
    except Exception as e:
        print("request_host_control error:", e)
        return False

def release_control(session_id):
    url = f"{BASE_URL}/hostControl/releaseControl"
    try:
        r = requests.post(url, json={"sessionId": session_id}, verify=False)
        print("releaseControl:", r.status_code, getattr(r, "text", ""))
    except Exception as e:
        print("release_control error:", e)

def get_te_state(session_id):
    url = f"{BASE_URL}/templateExecution/getState?sessionId={session_id}"
    try:
        r = requests.get(url, verify=False)
        return r.json().get("value", {}) if r.status_code == 200 else {}
    except Exception as e:
        print("getState (TE) error:", e)
        return {}

def is_scanning(session_id):
    st = get_te_state(session_id)
    return st.get("executionState") == "scanning"

def _is_valid_template_id(tid: str) -> bool:
    return bool(tid) and tid != "00000000-0000-0000-0000-000000000000"

def capture_running_template(session_id):
    st = get_te_state(session_id)
    rt = st.get("runningTemplate") or {}
    tid, lbl = rt.get("id"), (rt.get("label") or "")
    state = (st.get("executionState") or "").lower()

    active_states = {"preparing", "scanning", "pausing", "continuing"}
    if _is_valid_template_id(tid) and (state in active_states or lbl):
        if tid != last_template.get("id"):
            last_template["id"], last_template["label"] = tid, lbl
            print(f"Captured running template: id={tid} label={lbl} (state={state})")
        return tid

def open_template(session_id, template_id):
    url = f"{BASE_URL}/templateModification/open"
    r = requests.post(url, json={"sessionId": session_id, "id": template_id}, verify=False)
    try:
        js = r.json()
    except Exception:
        js = {"raw": r.text}
    ok = js.get("result", {}).get("success", False)
    if not ok:
        print("open template ->", ok, js.get("result", {}))
    return ok

def start_template(session_id, template_id):
    """Start the stored template. Print reason automatically if it fails."""
    url = f"{BASE_URL}/templateExecution/start"
    r = requests.post(url, json={"sessionId": session_id, "id": template_id}, verify=False)
    try:
        js = r.json()
    except Exception:
        js = {"raw": r.text}
    ok = js.get("result", {}).get("success", False)
    reason = js.get("result", {}).get("reason", "")
    if ok:
        print("start template -> OK")
        return True
    # try open->start if host requires it
    if isinstance(reason, str) and "open" in reason.lower():
        if open_template(session_id, template_id):
            r2 = requests.post(url, json={"sessionId": session_id, "id": template_id}, verify=False)
            js2 = r2.json() if r2.status_code == 200 else {}
            ok2 = js2.get("result", {}).get("success", False)
            reason2 = js2.get("result", {}).get("reason", "")
            print("start (after open) ->", ok2, reason2)
            return ok2
    print("start template -> FAILED — reason:", reason)
    return False

def get_number_of_slice_groups(session_id):
    url = f"{BASE_URL}/parameter/standard/getNumberOfSliceGroups?sessionId={session_id}"
    r = requests.get(url, verify=False); r.raise_for_status()
    return int(r.json().get("value", 1))

def get_slice_orientation_dcs(session_id, index):
    url = f"{BASE_URL}/parameter/standard/getSliceOrientationDcs?sessionId={session_id}&index={index}"
    r = requests.get(url, verify=False); r.raise_for_status()
    return r.json()

def get_slice_position_pcs(session_id, index):
    url = f"{BASE_URL}/parameter/standard/getSlicePositionPcs?sessionId={session_id}&index={index}"
    r = requests.get(url, verify=False); r.raise_for_status()
    return r.json().get("value", {"sag": 0.0, "cor": 0.0, "tra": 0.0})

def set_slice_position_pcs(session_id, index, sag, cor, tra):
    url = f"{BASE_URL}/parameter/standard/setSlicePositionPcs"
    body = {"sessionId": session_id, "index": index,
            "value": {"sag": float(sag), "cor": float(cor), "tra": float(tra)},
            "allowSideEffects": True}
    r = requests.post(url, json=body, verify=False)
    try:
        js = r.json()
    except Exception:
        js = {"raw": r.text}
    ok = js.get("result", {}).get("success", False)
    reason = js.get("result", {}).get("reason", "")
    if not ok:
        print("setSlicePositionPcs -> FAILED — reason:", reason, getattr(r, "text", ""))
    return ok

def discover_plane_indices(session_id):
    """Find which slice-group index best matches sag/cor/tra by normal vector."""
    out = {"sag": 0, "cor": 0, "tra": 0}
    best = {"sag": (-1, 0), "cor": (-1, 0), "tra": (-1, 0)}
    try:
        n = get_number_of_slice_groups(session_id)
    except Exception as e:
        print(f"getNumberOfSliceGroups failed: {e}")
        n = 1
    for i in range(max(1, n)):
        try:
            ori = get_slice_orientation_dcs(session_id, i)
            nx, ny, nz = (abs(ori.get("normal", {}).get(k, 0.0)) for k in ("x", "y", "z"))
            if nx > best["sag"][0]: best["sag"] = (nx, i)
            if ny > best["cor"][0]: best["cor"] = (ny, i)
            if nz > best["tra"][0]: best["tra"] = (nz, i)
        except Exception as e:
            print(f"getSliceOrientationDcs({i}) failed: {e}")
    out["sag"], out["cor"], out["tra"] = best["sag"][1], best["cor"][1], best["tra"][1]
    print("Plane indices:", out)
    return out

# ============================================================================


class CustomMainWindow(QMainWindow):
    def __init__(self):
        super(CustomMainWindow, self).__init__()

        self.setWindowTitle("TLv")

        # Create FRAME_A
        self.FRAME_A = QFrame(self)
        self.FRAME_A.setStyleSheet("background-color: black;")
        self.LAYOUT_A = QGridLayout()
        self.LAYOUT_A.setContentsMargins(0, 0, 0, 0)  # Remove margins
        self.LAYOUT_A.setSpacing(0)  # Remove spacing between widgets
        self.FRAME_A.setLayout(self.LAYOUT_A)
        self.setCentralWidget(self.FRAME_A)

        # Setup window with two labels to display images
        self.label_left = QLabel(self)
        self.label_right = QLabel(self)

        # Set size policy for the labels to expand dynamically
        self.label_left.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.label_right.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Set background color of labels to black
        self.label_left.setStyleSheet("background-color: black;")
        self.label_right.setStyleSheet("background-color: black;")

        # Add the labels to the layout without alignment to allow stretching
        self.LAYOUT_A.addWidget(self.label_left, 0, 0)
        self.LAYOUT_A.addWidget(self.label_right, 0, 1)

        # Brightness, contrast, and gamma levels for left and right images
        self.brightness_levels = {0: 0.0, 1: 0.0}  # 0 means no change
        self.contrast_levels = {0: 1.0, 1: 1.0}    # 1.0 means no change
        self.gamma_levels = {0: 1.0, 1: 1.0}       # Default gamma values

        # State variables for adjustment modes
        self.brightness_mode = False  # True when in brightness adjustment mode
        self.contrast_mode = False    # True when in contrast adjustment mode
        self.gamma_mode = False       # True when in gamma adjustment mode
        self.selected_image = None    # 0 for left, 1 for right

        # ================= NEW: host slice movement state =================
        self.session_id = None
        self.slice_mode = False            # toggle with S
        self.slice_step_mm = 2.0
        self.plane_indices = {"sag": 0, "cor": 0, "tra": 0}
        # =================================================================

        # Adjust the window to full screen based on the screen it's running on
        self.adjust_window_to_screen()

        # ================= NEW: auto poll to capture running template =====
        self._last_seen_tid = None
        self.template_poll = QTimer(self)
        self.template_poll.setInterval(1000)  # 1s
        self.template_poll.timeout.connect(self._poll_template_state)
        self.template_poll.start()
        # =================================================================

        # Show the window after adjustments
        self.show()

    # ================= NEW: template poller (auto-capture) ==============
    def _poll_template_state(self):
        if not self.session_id:
            return
        tid = capture_running_template(self.session_id)  # auto-captures and prints when changes
        # (No key needed; last_template is kept up to date automatically)
    # ====================================================================

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

    # ================= NEW: host slice helpers ===========================
    def ensure_plane_indices(self):
        if self.session_id:
            try:
                self.plane_indices = discover_plane_indices(self.session_id)
            except Exception as e:
                print("discover_plane_indices failed:", e)

    def move_slice_for_side(self, side, delta_mm):
        if self.session_id is None:
            return
        if is_scanning(self.session_id):
            print("Cannot move host slice while scanning.")
            return
        # Which axis is this pane showing? (fallback if unknown)
        axis = side_axis.get(side) or ("sag" if side == 0 else "cor")
        idx = self.plane_indices.get(axis, 0)
        try:
            pos = get_slice_position_pcs(self.session_id, idx)
            sag, cor, tra = pos["sag"], pos["cor"], pos["tra"]
            if axis == "sag": sag += delta_mm
            elif axis == "cor": cor += delta_mm
            else: tra += delta_mm
            if not request_host_control(self.session_id):
                return  # reason already printed
            if set_slice_position_pcs(self.session_id, idx, sag, cor, tra):
                print(f"[HOST] {('LEFT','RIGHT')[side]} {axis} += {delta_mm:.2f} mm "
                      f"? (sag={sag:.2f}, cor={cor:.2f}, tra={tra:.2f})")
        except Exception as e:
            print("Slice move failed:", e)
    # ====================================================================

    # Key press event handler to adjust brightness, contrast, and gamma
    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        print(f"Key pressed: {key}")
        if key == Qt.Key.Key_Escape:
            self.close()

        # ================= NEW: Host Ctrl / Start / Slice mode keys ======
        elif key == Qt.Key.Key_H:
            if self.session_id:
                request_host_control(self.session_id)  # auto prints reason if fails

        elif key == Qt.Key.Key_G:
            if self.session_id:
                release_control(self.session_id)

        elif key == Qt.Key.Key_O:
            # Optional manual capture (auto happens every 1s anyway)
            if self.session_id:
                capture_running_template(self.session_id)

        elif key == Qt.Key.Key_P:
            # Start last captured template (requires Host Control & not scanning)
            if self.session_id and last_template["id"]:
                if is_scanning(self.session_id):
                    print("Already scanning; cannot start.")
                else:
                    if not request_host_control(self.session_id):
                        pass  # reason printed
                    else:
                        start_template(self.session_id, last_template["id"])
            else:
                print("No captured template yet; wait for auto-capture while operator runs, or press O during run.")

        elif key == Qt.Key.Key_S:
            self.slice_mode = not self.slice_mode
            # turn off image adj modes when entering slice mode
            if self.slice_mode:
                self.brightness_mode = self.contrast_mode = self.gamma_mode = False
                self.ensure_plane_indices()
                print("Slice mode ON (L/R select pane; arrows move).")
            else:
                print("Slice mode OFF.")
        # ================================================================

        elif key == Qt.Key.Key_B:
            # Toggle brightness adjustment mode
            self.brightness_mode = not self.brightness_mode
            self.contrast_mode = False
            self.gamma_mode = False
            self.slice_mode = False
            print("Brightness mode toggled.")
        elif key == Qt.Key.Key_C:
            # Toggle contrast adjustment mode
            self.contrast_mode = not self.contrast_mode
            self.brightness_mode = False
            self.gamma_mode = False
            self.slice_mode = False
            print("Contrast mode toggled.")
        elif key == Qt.Key.Key_I:
            # Toggle gamma adjustment mode
            self.gamma_mode = not self.gamma_mode
            self.brightness_mode = False
            self.contrast_mode = False
            self.slice_mode = False
            print("Gamma mode toggled.")

        # ================= NEW: pane select independent of adj modes =====
        elif key == Qt.Key.Key_L:
            self.selected_image = 0
            print("Selected left image for adjustment / slice move.")
        elif key == Qt.Key.Key_R:
            self.selected_image = 1
            print("Selected right image for adjustment / slice move.")
        # ================================================================

        elif self.brightness_mode or self.contrast_mode or self.gamma_mode:
            if self.selected_image is not None:
                if key == Qt.Key.Key_Up:
                    # Increase adjustment
                    if self.brightness_mode:
                        self.adjust_brightness(self.selected_image, 10)
                    elif self.contrast_mode:
                        self.adjust_contrast(self.selected_image, 0.1)
                    elif self.gamma_mode:
                        self.adjust_gamma(self.selected_image, 0.1)
                elif key == Qt.Key.Key_Down:
                    # Decrease adjustment
                    if self.brightness_mode:
                        self.adjust_brightness(self.selected_image, -10)
                    elif self.contrast_mode:
                        self.adjust_contrast(self.selected_image, -0.1)
                    elif self.gamma_mode:
                        self.adjust_gamma(self.selected_image, -0.1)

        # ================= NEW: arrow keys for host slice movement =======
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            if self.slice_mode:
                if self.selected_image is None:
                    print("Pick a pane first (L or R).")
                    return
                delta = self.slice_step_mm if key in (Qt.Key.Key_Up, Qt.Key.Key_Right) else -self.slice_step_mm
                self.move_slice_for_side(self.selected_image, delta)
                return
            # else: if not in slice mode, arrows do nothing special (keep original behavior)
        # ================================================================

    def adjust_brightness(self, index, delta):
        # Update brightness level
        self.brightness_levels[index] += delta
        self.brightness_levels[index] = max(-100, min(self.brightness_levels[index], 100))
        print(f"Brightness level for image {index}: {self.brightness_levels[index]}")
        if original_images[index] is not None:
            self.update_image(original_images[index], index)

    def adjust_contrast(self, index, delta):
        # Update contrast level
        self.contrast_levels[index] += delta
        self.contrast_levels[index] = max(0.1, min(self.contrast_levels[index], 3.0))
        print(f"Contrast level for image {index}: {self.contrast_levels[index]}")
        if original_images[index] is not None:
            self.update_image(original_images[index], index)

    def adjust_gamma(self, index, delta):
        # Update gamma level
        self.gamma_levels[index] += delta
        self.gamma_levels[index] = max(0.1, self.gamma_levels[index])
        print(f"Gamma level for image {index}: {self.gamma_levels[index]}")
        if original_images[index] is not None:
            self.update_image(original_images[index], index)

    def update_image(self, image_array, index):
        """
        Update the displayed image in the QLabel using OpenCV with enhanced quality.
        """
        try:
            # Store original image
            original_images[index] = image_array.copy()

            # Normalize to 8-bit grayscale or color (to maintain precision)
            if image_array.dtype != np.uint8:
                image_array = cv2.normalize(
                    image_array, None, 0, 255, cv2.NORM_MINMAX
                ).astype(np.uint8)

            # Adjust contrast and brightness
            alpha = self.contrast_levels[index]  # Contrast control
            beta = self.brightness_levels[index]  # Brightness control
            image_array = cv2.convertScaleAbs(image_array, alpha=alpha, beta=beta)

            # Apply sharpening filter for better details
            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
            enhanced_image = cv2.filter2D(image_array, -1, kernel)

            # Apply gamma correction
            gamma = self.gamma_levels[index]
            image_array = apply_gamma_correction(image_array, gamma)

            # Convert grayscale to RGB
            if len(image_array.shape) == 2:  # Grayscale image
                image_rgb = cv2.cvtColor(image_array, cv2.COLOR_GRAY2RGB)
            elif len(image_array.shape) == 3 and image_array.shape[2] == 1:
                # Single-channel image
                image_rgb = cv2.cvtColor(image_array, cv2.COLOR_GRAY2RGB)
            elif len(image_array.shape) == 3 and image_array.shape[2] == 3:
                # Already RGB
                image_rgb = image_array
            else:
                print(f"Unsupported image shape: {image_array.shape}")
                return

            # Get the target label based on index
            if index == 0:
                label = self.label_left
            elif index == 1:
                label = self.label_right
            else:
                print(f"Invalid index: {index}")
                return

            # Get the size of the label
            label_width = label.width()
            label_height = label.height()
            print(f"Label size: width={label_width}, height={label_height}")

            # Ensure label dimensions are positive
            if label_width <= 0 or label_height <= 0:
                print(f"Label size is invalid: width={label_width}, height={label_height}")
                return

            # Get original image size
            img_height, img_width = image_rgb.shape[:2]

            # Compute scaling factor while maintaining aspect ratio
            width_ratio = label_width / img_width
            height_ratio = label_height / img_height

            # Use max to scale up the image to fill the label
            scaling_factor = max(width_ratio, height_ratio)
            print(f"Scaling factor: {scaling_factor}")

            # Ensure scaling_factor is positive
            if scaling_factor <= 0:
                print(f"Invalid scaling factor: {scaling_factor}")
                return

            # Compute new size
            new_width = max(1, int(img_width * scaling_factor))
            new_height = max(1, int(img_height * scaling_factor))

            # Resize image
            image_rgb_resized = cv2.resize(
                image_rgb, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4
            )

            # Crop the image to fit the label size
            x_offset = (new_width - label_width) // 2 if new_width > label_width else 0
            y_offset = (new_height - label_height) // 2 if new_height > label_height else 0
            image_cropped = image_rgb_resized[
                y_offset:y_offset + label_height,
                x_offset:x_offset + label_width
            ]

            # Convert the cropped image to QImage
            height, width, channel = image_cropped.shape
            bytes_per_line = channel * width

            # Convert the image data to bytes
            image_bytes = image_cropped.tobytes()

            # Create QImage from bytes
            q_img = QImage(
                image_bytes,
                width,
                height,
                bytes_per_line,
                QImage.Format.Format_RGB888,
            )

            # Convert QImage to QPixmap
            pixmap = QPixmap.fromImage(q_img)

            # Set the pixmap to the label
            label.setPixmap(pixmap)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        except Exception as e:
            print(f"An error occurred in update_image: {e}")

class Communicate(QObject):
    data_signal = pyqtSignal(np.ndarray, int)

# WebSocket-based function to process the image data
def process_image_data(value):
    global image_counter, last_image_time  # Access global variables

    if value is None:
        print("Received NoneType value, skipping processing.")
        return

    # Check if there's a significant pause in receiving images
    current_time = time.time()
    if last_image_time is not None and (current_time - last_image_time > image_pause_threshold):
        print("Pause detected in receiving images. Resetting counter.")
        image_counter = 0  # Reset the counter

    # Update the last image time
    last_image_time = current_time

    image_format = value.get("image", {}).get("format", "dicom")
    image_data_base64 = value.get("image", {}).get("data")

    if image_data_base64:
        image_data_byte = base64.b64decode(image_data_base64)

        if image_format == "dicom":

            # save raw DICOM bytes to disk
            filename = f"dicom_{int(time.time() * 1000)}_{image_counter}.dcm"
            file_path = os.path.join(SAVE_DIR, filename)
            try:
                with open(file_path, "wb") as f:
                    f.write(image_data_byte)
                print(f"Saved DICOM to {file_path}")
            except Exception as e:
                print(f"Could not save DICOM: {e}")

            dicom_file = BytesIO(image_data_byte)
            dicom_img = pydicom.dcmread(dicom_file)

            # Ensure pixel array is of correct type
            image_array = dicom_img.pixel_array
            print(
                f"Image shape: {image_array.shape}, dtype: {image_array.dtype}"
            )  # Debug info

            # ================= NEW: infer which axis this pane shows ======
            try:
                iop = dicom_img.get((0x0020, 0x0037), None)
                if iop and len(iop.value) == 6:
                    row = np.array(iop.value[0:3], dtype=float)
                    col = np.array(iop.value[3:6], dtype=float)
                    normal = np.cross(row, col)
                    ax = int(np.argmax(np.abs(normal)))
                    axis_name = {0: "sag", 1: "cor", 2: "tra"}[ax]
                else:
                    axis_name = None
            except Exception:
                axis_name = None
            pane = image_counter % 2  # 0 left, 1 right
            side_axis[pane] = axis_name
            # =============================================================

            # Add image and counter to the queue
            image_queue.put((image_array, pane))  # 0 for left, 1 for right
            image_counter += 1  # Increment the counter

        else:
            print(f"Unsupported image format: {image_format}")
    else:
        print("No image data found in the message.")

# WebSocket event handlers
def on_message(ws, message):
    try:
        if isinstance(message, bytes):
            print("Received binary data via WebSocket.")
        else:
            data = json.loads(message)
            service = data.get("service")
            response = data.get("response", {})
            value = response.get("value")

            if service == "product/image":
                print("Received an image message via WebSocket.")
                process_image_data(value)
            else:
                print(
                    f"WebSocket Message from {service}: {json.dumps(response, indent=4)}"
                )
                process_image_data(value)
    except json.JSONDecodeError:
        print(f"Received non-JSON message: {message}")
    except Exception as e:
        print(f"An error occurred in on_message: {e}")

def on_error(ws, error):
    print(f"WebSocket error: {error}")

# ================= NEW: correct signature =================
def on_close(ws, close_status_code, close_msg):
    print(f"WebSocket closed: {close_status_code} {close_msg}")
# ==========================================================

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

# Function to process the image queue and emit the signal
def process_image_queue():
    if not image_queue.empty():
        # Retrieve the image and the index (0 for left, 1 for right)
        image_array, index = image_queue.get()

        # Update the image on the corresponding label (left or right)
        comm.data_signal.emit(image_array, index)

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
        window.session_id = session_id  # ================= NEW: expose to window
        # Connect to WebSocket and start receiving images
        connect_websocket(session_id)
        # Enable WebSocket messages for the image service
        enable_websocket_messages(session_id)

    # Use QTimer to periodically process the image queue
    timer = QTimer()
    timer.timeout.connect(process_image_queue)
    timer.start(100)  # Update every 100 milliseconds

    # Start the Qt event loop
    app.exec()
