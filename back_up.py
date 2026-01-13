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

# ================= plane + template tracking =================
# Which axis each pane likely shows (auto-filled from DICOM headers)
side_axis = {0: None, 1: None}

# Remember last running template so we can restart it later (auto-captured)
last_template = {"id": None, "label": None}
# ============================================================


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

# ------------------------- Image helpers -------------------------

def apply_gamma_correction(image, gamma):
    inv_gamma = 1.0 / gamma
    table = np.array([(i / 255.0) ** inv_gamma * 255 for i in range(256)]).astype("uint8")
    return cv2.LUT(image, table)

# ============== Host Control + Template + Plane helpers ==============

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
    url = f"{BASE_URL}/hostControl/requestControl"
    try:
        r = requests.post(url, json={"sessionId": session_id}, verify=False)
        js = r.json() if r.status_code == 200 else {}
        ok = js.get("result", {}).get("success", False)
        reason = (js.get("result", {}).get("reason") or "").strip()

        if ok:
            print("Host control request OK")
            return True

        #if we’re already in control, treat as success
        state = get_hc_state(session_id)
        has_ctrl = bool(state.get("hasControl"))
        if reason == "clientInControl" or has_ctrl:
            print("Already have Host Control")
            return True

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
    """Sticky capture: keep last valid, never overwrite with zero/idle."""
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
    return last_template.get("id")

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

# --------- NEW: stop + wait helpers for Option B (stop→move→restart) ---------

def stop_current(session_id):
    url = f"{BASE_URL}/templateExecution/stop"
    try:
        r = requests.post(url, json={"sessionId": session_id}, verify=False)
        js = r.json() if r.status_code == 200 else {}
        ok = js.get("result", {}).get("success", False)
        print("stop ->", ok, js.get("result", {}))
        return ok
    except Exception as e:
        print("stop_current error:", e)
        return False

def wait_until_not_scanning(session_id, timeout_ms=5000, poll_ms=100):
    deadline = time.time() + timeout_ms/1000.0
    while time.time() < deadline:
        if not is_scanning(session_id):
            return True
        time.sleep(poll_ms/1000.0)
    print("Timeout waiting for scan to stop.")
    return False

# ============================================================================


class CustomMainWindow(QMainWindow):
    def __init__(self):
        super(CustomMainWindow, self).__init__()

        self.setWindowTitle("TLv")

        # Create FRAME_A
        self.FRAME_A = QFrame(self)
        self.FRAME_A.setStyleSheet("background-color: black;")
        self.LAYOUT_A = QGridLayout()
        self.LAYOUT_A.setContentsMargins(0, 0, 0, 0)
        self.LAYOUT_A.setSpacing(0)
        self.FRAME_A.setLayout(self.LAYOUT_A)
        self.setCentralWidget(self.FRAME_A)

        # Setup window with two labels to display images
        self.label_left = QLabel(self)
        self.label_right = QLabel(self)

        self.label_left.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.label_right.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.label_left.setStyleSheet("background-color: black;")
        self.label_right.setStyleSheet("background-color: black;")

        self.LAYOUT_A.addWidget(self.label_left, 0, 0)
        self.LAYOUT_A.addWidget(self.label_right, 0, 1)

        # Brightness, contrast, and gamma levels
        self.brightness_levels = {0: 0.0, 1: 0.0}
        self.contrast_levels = {0: 1.0, 1: 1.0}
        self.gamma_levels = {0: 1.0, 1: 1.0}

        # State variables for adjustment modes
        self.brightness_mode = False
        self.contrast_mode = False
        self.gamma_mode = False
        self.selected_image = None  # 0 for left, 1 for right

        # Host slice movement state
        self.session_id = None
        self.slice_mode = False            # toggle with S
        self.slice_step_mm = 2.0
        self.plane_indices = {"sag": 0, "cor": 0, "tra": 0}

        # Re-entrancy guard for stop→move→restart
        self._arrow_busy = False

        # Maximize to the current screen
        self.adjust_window_to_screen()

        # Auto poll to capture running template
        self._last_seen_tid = None
        self.template_poll = QTimer(self)
        self.template_poll.setInterval(1000)  # 1s
        self.template_poll.timeout.connect(self._poll_template_state)
        self.template_poll.start()

        self.show()

    # Template poller (auto-capture)
    def _poll_template_state(self):
        if not self.session_id:
            return
        capture_running_template(self.session_id)

    def adjust_window_to_screen(self):
        screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.geometry()
            self.setGeometry(geometry)
        else:
            print("No screen information available.")

    def showEvent(self, event):
        super(CustomMainWindow, self).showEvent(event)
        self.adjust_window_to_screen()

    # Host slice helpers
    def ensure_plane_indices(self):
        if self.session_id:
            try:
                self.plane_indices = discover_plane_indices(self.session_id)
            except Exception as e:
                print("discover_plane_indices failed:", e)

    # --------- MODIFIED: stop→move→restart if scanning; else just move ---------
    def move_slice_for_side(self, side, delta_mm):
        if self.session_id is None:
            return

        if self._arrow_busy:
            print("Busy applying previous move…")
            return
        self._arrow_busy = True
        try:
            was_scanning = is_scanning(self.session_id)
            if was_scanning:
                print("Stopping scan to apply plane move…")
                if not stop_current(self.session_id):
                    print("Stop failed; cannot apply move.")
                    return
                if not wait_until_not_scanning(self.session_id):
                    return

            # Ensure indices + captured template
            self.ensure_plane_indices()
            if not _is_valid_template_id(last_template.get("id")):
                capture_running_template(self.session_id)

            # Which axis is this pane showing? (fallback if unknown)
            axis = side_axis.get(side) or ("sag" if side == 0 else "cor")
            idx = self.plane_indices.get(axis, 0)
            try:
                pos = get_slice_position_pcs(self.session_id, idx)
                sag, cor, tra = pos["sag"], pos["cor"], pos["tra"]
                if axis == "sag": sag += delta_mm
                elif axis == "cor": cor += delta_mm
                else: tra += delta_mm

                # Re-request control to ensure ownership after stop
                if not request_host_control(self.session_id):
                    return  # reason already printed

                if set_slice_position_pcs(self.session_id, idx, sag, cor, tra):
                    print(f"[HOST] {('LEFT','RIGHT')[side]} {axis} += {delta_mm:.2f} mm "
                          f"→ (sag={sag:.2f}, cor={cor:.2f}, tra={tra:.2f})")
                else:
                    return
            except Exception as e:
                print("Slice move failed:", e)
                return

            # Restart only if we stopped a running scan
            if was_scanning:
                tid = last_template.get("id")
                if _is_valid_template_id(tid):
                    print("Restarting captured protocol…")
                    start_template(self.session_id, tid)
                else:
                    print("No valid captured template to restart.")
        finally:
            self._arrow_busy = False

    # Key press handler
    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        print(f"Key pressed: {key}")
        if key == Qt.Key.Key_Escape:
            self.close()

        # Host Ctrl / Start / Slice mode keys
        elif key == Qt.Key.Key_H:
            if self.session_id:
                request_host_control(self.session_id)

        elif key == Qt.Key.Key_G:
            if self.session_id:
                release_control(self.session_id)

        elif key == Qt.Key.Key_O:
            if self.session_id:
                capture_running_template(self.session_id)


        elif key == Qt.Key.Key_P:

            if not self.session_id:
                return

            if not last_template["id"]:
                print("No captured template yet; let the operator start once or press O during run.")

                return

            if is_scanning(self.session_id):
                print("Already scanning; cannot start.")

                return

            # NEW: only request control if we don't already have it

            hc = get_hc_state(self.session_id)

            if not hc.get("hasControl", False):

                if not request_host_control(self.session_id):
                    return  # reason already printed

            start_template(self.session_id, last_template["id"])
        elif key == Qt.Key.Key_S:
            self.slice_mode = not self.slice_mode
            if self.slice_mode:
                self.brightness_mode = self.contrast_mode = self.gamma_mode = False
                self.ensure_plane_indices()
                print("Slice mode ON (L/R select pane; arrows move).")
            else:
                print("Slice mode OFF.")

        # Image adjustment modes
        elif key == Qt.Key.Key_B:
            self.brightness_mode = not self.brightness_mode
            self.contrast_mode = False
            self.gamma_mode = False
            self.slice_mode = False
            print("Brightness mode toggled.")

        elif key == Qt.Key.Key_C:
            self.contrast_mode = not self.contrast_mode
            self.brightness_mode = False
            self.gamma_mode = False
            self.slice_mode = False
            print("Contrast mode toggled.")

        elif key == Qt.Key.Key_I:
            self.gamma_mode = not self.gamma_mode
            self.brightness_mode = False
            self.contrast_mode = False
            self.slice_mode = False
            print("Gamma mode toggled.")

        # Pane select
        elif key == Qt.Key.Key_L:
            self.selected_image = 0
            print("Selected left image for adjustment / slice move.")
        elif key == Qt.Key.Key_R:
            self.selected_image = 1
            print("Selected right image for adjustment / slice move.")

        # Arrow keys: move planes
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            if not self.slice_mode:
                return
            if self.selected_image is None:
                print("Pick a pane first (L or R).")
                return
            delta = self.slice_step_mm if key in (Qt.Key.Key_Up, Qt.Key.Key_Right) else -self.slice_step_mm
            self.move_slice_for_side(self.selected_image, delta)
            return

        # Image adjustments with arrows (if in those modes)
        elif self.brightness_mode or self.contrast_mode or self.gamma_mode:
            if self.selected_image is not None:
                if key == Qt.Key.Key_Up:
                    if self.brightness_mode:
                        self.adjust_brightness(self.selected_image, 10)
                    elif self.contrast_mode:
                        self.adjust_contrast(self.selected_image, 0.1)
                    elif self.gamma_mode:
                        self.adjust_gamma(self.selected_image, 0.1)
                elif key == Qt.Key.Key_Down:
                    if self.brightness_mode:
                        self.adjust_brightness(self.selected_image, -10)
                    elif self.contrast_mode:
                        self.adjust_contrast(self.selected_image, -0.1)
                    elif self.gamma_mode:
                        self.adjust_gamma(self.selected_image, -0.1)

    # Image adjustments
    def adjust_brightness(self, index, delta):
        self.brightness_levels[index] += delta
        self.brightness_levels[index] = max(-100, min(self.brightness_levels[index], 100))
        print(f"Brightness level for image {index}: {self.brightness_levels[index]}")
        if original_images[index] is not None:
            self.update_image(original_images[index], index)

    def adjust_contrast(self, index, delta):
        self.contrast_levels[index] += delta
        self.contrast_levels[index] = max(0.1, min(self.contrast_levels[index], 3.0))
        print(f"Contrast level for image {index}: {self.contrast_levels[index]}")
        if original_images[index] is not None:
            self.update_image(original_images[index], index)

    def adjust_gamma(self, index, delta):
        self.gamma_levels[index] += delta
        self.gamma_levels[index] = max(0.1, self.gamma_levels[index])
        print(f"Gamma level for image {index}: {self.gamma_levels[index]}")
        if original_images[index] is not None:
            self.update_image(original_images[index], index)

    def update_image(self, image_array, index):
        try:
            original_images[index] = image_array.copy()

            if image_array.dtype != np.uint8:
                image_array = cv2.normalize(
                    image_array, None, 0, 255, cv2.NORM_MINMAX
                ).astype(np.uint8)

            alpha = self.contrast_levels[index]
            beta = self.brightness_levels[index]
            image_array = cv2.convertScaleAbs(image_array, alpha=alpha, beta=beta)

            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
            enhanced_image = cv2.filter2D(image_array, -1, kernel)

            gamma = self.gamma_levels[index]
            image_array = apply_gamma_correction(image_array, gamma)

            if len(image_array.shape) == 2:
                image_rgb = cv2.cvtColor(image_array, cv2.COLOR_GRAY2RGB)
            elif len(image_array.shape) == 3 and image_array.shape[2] == 1:
                image_rgb = cv2.cvtColor(image_array, cv2.COLOR_GRAY2RGB)
            elif len(image_array.shape) == 3 and image_array.shape[2] == 3:
                image_rgb = image_array
            else:
                print(f"Unsupported image shape: {image_array.shape}")
                return

            if index == 0:
                label = self.label_left
            elif index == 1:
                label = self.label_right
            else:
                print(f"Invalid index: {index}")
                return

            label_width = label.width()
            label_height = label.height()
            print(f"Label size: width={label_width}, height={label_height}")

            if label_width <= 0 or label_height <= 0:
                print(f"Label size is invalid: width={label_width}, height={label_height}")
                return

            img_height, img_width = image_rgb.shape[:2]

            width_ratio = label_width / img_width
            height_ratio = label_height / img_height

            scaling_factor = max(width_ratio, height_ratio)
            print(f"Scaling factor: {scaling_factor}")

            if scaling_factor <= 0:
                print(f"Invalid scaling factor: {scaling_factor}")
                return

            new_width = max(1, int(img_width * scaling_factor))
            new_height = max(1, int(img_height * scaling_factor))

            image_rgb_resized = cv2.resize(
                image_rgb, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4
            )

            x_offset = (new_width - label_width) // 2 if new_width > label_width else 0
            y_offset = (new_height - label_height) // 2 if new_height > label_height else 0
            image_cropped = image_rgb_resized[
                y_offset:y_offset + label_height,
                x_offset:x_offset + label_width
            ]

            height, width, channel = image_cropped.shape
            bytes_per_line = channel * width
            image_bytes = image_cropped.tobytes()

            q_img = QImage(
                image_bytes,
                width,
                height,
                bytes_per_line,
                QImage.Format.Format_RGB888,
            )

            pixmap = QPixmap.fromImage(q_img)
            label.setPixmap(pixmap)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        except Exception as e:
            print(f"An error occurred in update_image: {e}")

class Communicate(QObject):
    data_signal = pyqtSignal(np.ndarray, int)

# WebSocket-based function to process the image data
def process_image_data(value):
    global image_counter, last_image_time

    if value is None:
        print("Received NoneType value, skipping processing.")
        return

    current_time = time.time()
    if last_image_time is not None and (current_time - last_image_time > image_pause_threshold):
        print("Pause detected in receiving images. Resetting counter.")
        image_counter = 0

    last_image_time = current_time

    image_format = value.get("image", {}).get("format", "dicom")
    image_data_base64 = value.get("image", {}).get("data")

    if image_data_base64:
        image_data_byte = base64.b64decode(image_data_base64)

        if image_format == "dicom":
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

            image_array = dicom_img.pixel_array
            print(f"Image shape: {image_array.shape}, dtype: {image_array.dtype}")

            # Infer which axis this pane shows from Image Orientation (Patient)
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

            image_queue.put((image_array, pane))
            image_counter += 1

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
                print(f"WebSocket Message from {service}: {json.dumps(response, indent=4)}")
                process_image_data(value)
    except json.JSONDecodeError:
        print(f"Received non-JSON message: {message}")
    except Exception as e:
        print(f"An error occurred in on_message: {e}")

def on_error(ws, error):
    print(f"WebSocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"WebSocket closed: {close_status_code} {close_msg}")

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
        image_array, index = image_queue.get()
        comm.data_signal.emit(image_array, index)

# Main process
if __name__ == "__main__":
    if not is_server_active():
        print("Exiting due to inactive server.")
        exit(1)

    app = QApplication([])

    window = CustomMainWindow()

    comm = Communicate()
    comm.data_signal.connect(window.update_image)

    session_id = get_session_id()
    if session_id:
        window.session_id = session_id
        connect_websocket(session_id)
        enable_websocket_messages(session_id)

    timer = QTimer()
    timer.timeout.connect(process_image_queue)
    timer.start(100)

    app.exec()
