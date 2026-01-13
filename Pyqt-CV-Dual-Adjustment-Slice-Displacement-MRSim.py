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
import time
import os
import re

# ====== CONFIG ======
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
BASE_URL = "https://10.243.146.24:7787/SRC/v2/product"
WEBSOCKET_URL = "wss://10.243.146.24:7788/SRC"
SAVE_DIR = "Saved_DICOMs"
os.makedirs(SAVE_DIR, exist_ok=True)

# ====== IMAGE FLOW STATE ======
last_image_time = None
image_pause_threshold = 5
image_queue = Queue()
image_counter = 0
original_images = {0: None, 1: None}
gamma_levels = {0: 1.0, 1: 1.0}
side_axis = {0: None, 1: None}
last_template = {"id": None, "label": None}

# ====== GUID helper ======
GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
def _is_guid(v: str) -> bool:
    return isinstance(v, str) and bool(GUID_RE.fullmatch(v))

# ------------------------- HTTP helpers -------------------------
def _get(ep, params=None):
    url = f"{BASE_URL}/{ep}"
    r = requests.get(url, params=params or {}, verify=False)
    try:
        js = r.json()
    except Exception:
        js = {"raw": r.text}
    return r.status_code, js

def _post(ep, body):
    url = f"{BASE_URL}/{ep}"
    r = requests.post(url, json=body, verify=False)
    try:
        js = r.json()
    except Exception:
        js = {"raw": r.text}
    ok = js.get("result", {}).get("success", False)
    reason = js.get("result", {}).get("reason", "")
    print(f"{ep} -> ok={ok} reason='{reason}'")
    return ok, reason, js

# ------------------------- Access-i session -------------------------
def is_server_active():
    st, js = _get("remote/getIsActive")
    if st == 200:
        is_active = js.get("value", False)
        print(f"Server is {'active' if is_active else 'inactive'}.")
        return is_active
    print(f"Failed to check server status. Status code: {st}")
    return False

def get_session_id():
    auth_url = f"{BASE_URL}/authorization/register"
    body = {
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
        r = requests.post(auth_url, json=body, verify=False)
        if r.status_code == 200:
            sid = r.json().get("sessionId")
            if sid:
                print("Session ID:", sid)
                return sid
            print("Session ID missing in response.")
        else:
            print("Failed to register:", r.status_code, r.text)
    except requests.exceptions.RequestException as e:
        print("Register error:", e)
    return None

def enable_websocket_messages(session_id):
    _post("Image/connectServiceToDefaultWebSocket", {"sessionId": session_id})

# ------------------------- Host control / execution -------------------------
def get_hc_state(session_id):
    st, js = _get("hostControl/getState", {"sessionId": session_id})
    return js.get("value", {}) if st == 200 else {}

def request_host_control(session_id):
    ok, reason, _ = _post("hostControl/requestControl", {"sessionId": session_id})
    if ok:
        print("Host control request OK")
        return True
    state = get_hc_state(session_id)
    if reason == "clientInControl" or bool(state.get("hasControl")):
        print("Already have Host Control")
        return True
    print(f"Host control request FAILED — reason: {reason or state.get('cannotRequestControlReason')}")
    return False

def release_control(session_id):
    ok, reason, js = _post("hostControl/releaseControl", {"sessionId": session_id})
    print(f"releaseControl: {js}")
    return ok, reason

def get_te_state(session_id):
    st, js = _get("templateExecution/getState", {"sessionId": session_id})
    return js.get("value", {}) if st == 200 else {}

def is_scanning(session_id):
    return (get_te_state(session_id).get("executionState") == "scanning")

def _is_valid_template_id(tid: str) -> bool:
    return _is_guid(tid) and tid != "00000000-0000-0000-0000-000000000000"

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
    return last_template.get("id")

def open_template(session_id, template_id):
    ok, _, _ = _post("templateModification/open", {"sessionId": session_id, "id": template_id})
    return ok

def start_template(session_id, template_id):
    ok, reason, _ = _post("templateExecution/start", {"sessionId": session_id, "id": template_id})
    if ok:
        print("start template -> OK")
        return True
    if isinstance(reason, str) and "open" in reason.lower():
        if open_template(session_id, template_id):
            ok2, r2, _ = _post("templateExecution/start", {"sessionId": session_id, "id": template_id})
            print("start (after open) ->", ok2, r2)
            return ok2
    print("start template -> FAILED — reason:", reason)
    return False

def stop_scanning(session_id):
    ok, reason, _ = _post("templateExecution/stop", {"sessionId": session_id})
    print(f"stop -> {ok} reason: {reason}")
    return ok

def wait_until_not_scanning(session_id, timeout_ms=5000, poll_ms=100):
    deadline = time.time() + timeout_ms/1000.0
    while time.time() < deadline:
        if not is_scanning(session_id):
            return True
        time.sleep(poll_ms/1000.0)
    print("Timeout waiting for scan to stop.")
    return False

# ------------------------- Parameter (slice) helpers -------------------------
def get_number_of_slice_groups(session_id):
    st, js = _get("parameter/standard/getNumberOfSliceGroups", {"sessionId": session_id})
    if st == 200:
        return int(js.get("value", 1))
    return 1

def get_slice_orientation_dcs(session_id, index):
    st, js = _get("parameter/standard/getSliceOrientationDcs", {"sessionId": session_id, "index": index})
    return js if st == 200 else {}

def get_slice_position_pcs(session_id, index):
    st, js = _get("parameter/standard/getSlicePositionPcs", {"sessionId": session_id, "index": index})
    return js.get("value", {"sag": 0.0, "cor": 0.0, "tra": 0.0}) if st == 200 else {"sag":0,"cor":0,"tra":0}

def set_slice_position_pcs(session_id, index, sag, cor, tra):
    ok, reason, _ = _post("parameter/standard/setSlicePositionPcs", {
        "sessionId": session_id,
        "index": index,
        "value": {"sag": float(sag), "cor": float(cor), "tra": float(tra)},
        "allowSideEffects": True
    })
    if not ok:
        print("setSlicePositionPcs -> FAILED — reason:", reason)
    return ok

def discover_plane_indices(session_id):
    out = {"sag": 0, "cor": 0, "tra": 0}
    best = {"sag": (-1, 0), "cor": (-1, 0), "tra": (-1, 0)}
    try:
        n = get_number_of_slice_groups(session_id)
    except Exception:
        n = 1
    for i in range(max(1, n)):
        try:
            ori = get_slice_orientation_dcs(session_id, i)
            nx, ny, nz = (abs(ori.get("normal", {}).get(k, 0.0)) for k in ("x","y","z"))
            if nx > best["sag"][0]: best["sag"] = (nx, i)
            if ny > best["cor"][0]: best["cor"] = (ny, i)
            if nz > best["tra"][0]: best["tra"] = (nz, i)
        except Exception:
            pass
    out["sag"], out["cor"], out["tra"] = best["sag"][1], best["cor"][1], best["tra"][1]
    print("Plane indices:", out)
    return out

# ------------------------- TemplateModification state & aggressive close -------------------------
def get_tm_state(session_id):
    st, js = _get("templateModification/getState", {"sessionId": session_id})
    val = js.get("value", js) if st == 200 else {}
    try:
        s = json.dumps(val, indent=2)
        print("TM state:", (s if len(s) < 2000 else s[:2000] + "…"))
    except Exception:
        pass
    return val

def _collect_ids_from_tm_state(val):
    ids = set()
    def walk(x):
        if isinstance(x, dict):
            for k in ("id", "templateId", "openTemplateId"):
                v = x.get(k)
                if isinstance(v, str) and _is_guid(v):
                    ids.add(v)
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
        elif isinstance(x, str):
            if _is_guid(x): ids.add(x)
    walk(val)
    return list(ids)

def _apply_commit_discard(session_id, discard_first=False):
    # optional discardChanges endpoint (some builds expose it)
    if discard_first:
        for ep in ("templateModification/discardChanges", "templateModification/revert"):
            ok, _, _ = _post(ep, {"sessionId": session_id})
            if ok: break
    # then apply/commit variants
    for ep in ("templateModification/apply", "templateModification/commit"):
        for payload in (
            {"sessionId": session_id},
            {"sessionId": session_id, "discardChanges": False},
            {"sessionId": session_id, "discardChanges": True},
        ):
            ok, _, _ = _post(ep, payload)
            if ok: break

def close_any_open_step(session_id, discard_first=False):
    tm = get_tm_state(session_id) or {}
    ot = (tm.get("openTemplate") or {})
    open_id = ot.get("id")
    can_close = bool(tm.get("canClose", False))
    print(f"[close] can_close={can_close} open_id={open_id} isInteractive={ot.get('isInteractive')}")

    # Also check TE state
    te = get_te_state(session_id) or {}
    rt = te.get("runningTemplate") or {}
    if not _is_guid(open_id) and _is_guid(rt.get("id")):
        open_id = rt.get("id")

    # Pull any GUIDs we can find (some builds hide it in nested fields)
    id_pool = _collect_ids_from_tm_state(tm)
    if _is_guid(open_id) and open_id not in id_pool:
        id_pool.append(open_id)
    if _is_guid(rt.get("id")) and rt["id"] not in id_pool:
        id_pool.append(rt["id"])
    if not id_pool:
        id_pool = [None]  # try close-without-id fallbacks

    # 1) Make sure host isn’t mid-scan interaction
    if is_scanning(session_id):
        stop_scanning(session_id)
        wait_until_not_scanning(session_id)

    # 2) safe apply/commit/discard sweep
    _apply_commit_discard(session_id, discard_first=discard_first)

    # 3) Close attempts (with id, with templateId, and no id)
    base = {"sessionId": session_id}
    close_endpoints = [
        "templateModification/closeTemplate",
        "templateModification/close",
        "templateModification/closeStep",
    ]
    payload_variants = []
    for tid in id_pool:
        if _is_guid(tid):
            payload_variants += [
                dict(base, id=tid),
                dict(base, id=tid, discardChanges=False),
                dict(base, id=tid, discardChanges=True),
                dict(base, templateId=tid),
                dict(base, templateId=tid, discardChanges=False),
                dict(base, templateId=tid, discardChanges=True),
            ]
    payload_variants += [base, dict(base, discardChanges=False), dict(base, discardChanges=True)]
    for ep in close_endpoints:
        for payload in payload_variants:
            ok, reason, _ = _post(ep, payload)
            if ok:
                return True
            if isinstance(reason, str) and reason.lower() in ("alreadyclosed", "notopen", "ok"):
                return True

    # 4) Interaction/step terminators (no-id, just sessionId)
    fallbacks = [
        "templateExecution/endInteraction",
        "templateExecution/finish",
        "templateExecution/end",
        "templateExecution/closeStep",
        "templateExecution/cancel",
        "templateExecution/abortStep",
        "step/close",
    ]
    for ep in fallbacks:
        ok, _, _ = _post(ep, {"sessionId": session_id})
        if ok:
            return True

    return False

# ------------------------- Viewer -------------------------
def apply_gamma_correction(image, gamma):
    inv_gamma = 1.0 / gamma
    table = np.array([(i / 255.0) ** inv_gamma * 255 for i in range(256)]).astype("uint8")
    return cv2.LUT(image, table)

class CustomMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TLv")

        self.FRAME_A = QFrame(self)
        self.FRAME_A.setStyleSheet("background-color: black;")
        self.LAYOUT_A = QGridLayout()
        self.LAYOUT_A.setContentsMargins(0, 0, 0, 0)
        self.LAYOUT_A.setSpacing(0)
        self.FRAME_A.setLayout(self.LAYOUT_A)
        self.setCentralWidget(self.FRAME_A)

        self.label_left = QLabel(self)
        self.label_right = QLabel(self)
        self.label_left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.label_right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.label_left.setStyleSheet("background-color: black;")
        self.label_right.setStyleSheet("background-color: black;")
        self.LAYOUT_A.addWidget(self.label_left, 0, 0)
        self.LAYOUT_A.addWidget(self.label_right, 0, 1)

        self.brightness_levels = {0: 0.0, 1: 0.0}
        self.contrast_levels = {0: 1.0, 1: 1.0}
        self.gamma_levels = {0: 1.0, 1: 1.0}

        self.brightness_mode = False
        self.contrast_mode = False
        self.gamma_mode = False
        self.selected_image = None

        self.session_id = None
        self.slice_mode = False
        self.slice_step_mm = 3.0
        self.plane_indices = {"sag": 0, "cor": 0, "tra": 0}

        self.adjust_window_to_screen()

        self.template_poll = QTimer(self)
        self.template_poll.setInterval(1000)
        self.template_poll.timeout.connect(self._poll_template_state)
        self.template_poll.start()

        self.show()

    def _poll_template_state(self):
        if self.session_id:
            capture_running_template(self.session_id)

    def adjust_window_to_screen(self):
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())

    def showEvent(self, event):
        super().showEvent(event)
        self.adjust_window_to_screen()

    # ---- slice helpers ----
    def ensure_plane_indices(self):
        if self.session_id:
            try:
                self.plane_indices = discover_plane_indices(self.session_id)
            except Exception as e:
                print("discover_plane_indices failed:", e)

    def move_slice_for_side(self, side, delta_mm):
        if not self.session_id:
            print("No session id; cannot move slice.")
            return
        self.ensure_plane_indices()
        axis = side_axis.get(side) or ("sag" if side == 0 else "cor")
        idx = self.plane_indices.get(axis, 0)
        try:
            pos = get_slice_position_pcs(self.session_id, idx)
            sag, cor, tra = pos["sag"], pos["cor"], pos["tra"]
            if axis == "sag": sag += delta_mm
            elif axis == "cor": cor += delta_mm
            else: tra += delta_mm
            if not request_host_control(self.session_id):
                return
            if set_slice_position_pcs(self.session_id, idx, sag, cor, tra):
                print(f"[HOST] {('LEFT','RIGHT')[side]} {axis} += {delta_mm:.2f} mm "
                      f"? (sag={sag:.2f}, cor={cor:.2f}, tra={tra:.2f})")
        except Exception as e:
            print("Slice move failed:", e)

    # ---- keys ----
    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        mods = event.modifiers()
        print(f"Key pressed: {key}")

        if key == Qt.Key.Key_Escape:
            self.close()

        elif key == Qt.Key.Key_H:
            if self.session_id:
                request_host_control(self.session_id)

        elif key == Qt.Key.Key_G:
            if not self.session_id:
                return
            # If scanning, stop first.
            if is_scanning(self.session_id):
                print("Scanning detected ? stopping before release…")
                stop_scanning(self.session_id)
                wait_until_not_scanning(self.session_id)
            # Try closing any open step/template
            aggressive = bool(mods & Qt.ShiftModifier)  # Shift+G = more aggressive (discard-first)
            closed = close_any_open_step(self.session_id, discard_first=aggressive)
            if not closed:
                print("Could not close open step via known endpoints; proceeding to release anyway.")
            ok, reason = release_control(self.session_id)
            if not ok:
                print(f"Give-away failed (reason='{reason}'). If 'clientNotInControl', control was already free.")

        elif key == Qt.Key.Key_K:
            if self.session_id:
                if stop_scanning(self.session_id):
                    wait_until_not_scanning(self.session_id)

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
            hc = get_hc_state(self.session_id)
            if not hc.get("hasControl", False):
                if not request_host_control(self.session_id):
                    return
            start_template(self.session_id, last_template["id"])

        elif key == Qt.Key.Key_S:
            self.slice_mode = not self.slice_mode
            if self.slice_mode:
                self.brightness_mode = self.contrast_mode = self.gamma_mode = False
                self.ensure_plane_indices()
                print("Slice mode ON (L/R select pane; arrows move).")
            else:
                print("Slice mode OFF.")

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

        elif key == Qt.Key.Key_L:
            self.selected_image = 0
            print("Selected left image.")
        elif key == Qt.Key.Key_R:
            self.selected_image = 1
            print("Selected right image.")

        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            if self.slice_mode:
                if self.selected_image is None:
                    print("Pick a pane first (L or R).")
                    return
                delta = self.slice_step_mm if key in (Qt.Key.Key_Up, Qt.Key.Key_Right) else -self.slice_step_mm
                self.move_slice_for_side(self.selected_image, delta)
                return
            if self.brightness_mode or self.contrast_mode or self.gamma_mode:
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

    # ---- image adjustments ----
    def adjust_brightness(self, index, delta):
        self.brightness_levels[index] += delta
        self.brightness_levels[index] = max(-100, min(self.brightness_levels[index], 100))
        print(f"Brightness[{index}] -> {self.brightness_levels[index]}")
        if original_images[index] is not None:
            self.update_image(original_images[index], index)

    def adjust_contrast(self, index, delta):
        self.contrast_levels[index] += delta
        self.contrast_levels[index] = max(0.1, min(self.contrast_levels[index], 3.0))
        print(f"Contrast[{index}] -> {self.contrast_levels[index]}")
        if original_images[index] is not None:
            self.update_image(original_images[index], index)

    def adjust_gamma(self, index, delta):
        self.gamma_levels[index] += delta
        self.gamma_levels[index] = max(0.1, self.gamma_levels[index])
        print(f"Gamma[{index}] -> {self.gamma_levels[index]}")
        if original_images[index] is not None:
            self.update_image(original_images[index], index)

    def update_image(self, image_array, index):
        try:
            original_images[index] = image_array.copy()
            if image_array.dtype != np.uint8:
                image_array = cv2.normalize(image_array, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            alpha = self.contrast_levels[index]
            beta = self.brightness_levels[index]
            image_array = cv2.convertScaleAbs(image_array, alpha=alpha, beta=beta)
            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
            image_array = cv2.filter2D(image_array, -1, kernel)
            gamma = self.gamma_levels[index]
            image_array = apply_gamma_correction(image_array, gamma)
            if len(image_array.shape) == 2:
                image_rgb = cv2.cvtColor(image_array, cv2.COLOR_GRAY2RGB)
            elif len(image_array.shape) == 3 and image_array.shape[2] == 1:
                image_rgb = cv2.cvtColor(image_array, cv2.COLOR_GRAY2RGB)
            elif len(image_array.shape) == 3 and image_array.shape[2] == 3:
                image_rgb = image_array
            else:
                print("Unsupported image shape:", image_array.shape)
                return
            label = self.label_left if index == 0 else self.label_right
            label_w, label_h = label.width(), label.height()
            if label_w <= 0 or label_h <= 0:
                return
            h, w = image_rgb.shape[:2]
            scale = max(label_w / w, label_h / h)
            new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
            image_resized = cv2.resize(image_rgb, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
            x_off = (new_w - label_w) // 2 if new_w > label_w else 0
            y_off = (new_h - label_h) // 2 if new_h > label_h else 0
            image_cropped = image_resized[y_off:y_off + label_h, x_off:x_off + label_w]
            h2, w2, ch = image_cropped.shape
            q_img = QImage(image_cropped.tobytes(), w2, h2, ch * w2, QImage.Format.Format_RGB888)
            label.setPixmap(QPixmap.fromImage(q_img))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        except Exception as e:
            print("update_image error:", e)

class Communicate(QObject):
    data_signal = pyqtSignal(np.ndarray, int)

# ------------------------- WebSocket image handling -------------------------
def process_image_data(value):
    global image_counter, last_image_time
    if value is None:
        return
    now = time.time()
    if last_image_time is not None and (now - last_image_time > image_pause_threshold):
        print("Pause detected in images. Resetting pane counter.")
        image_counter = 0
    last_image_time = now
    image_format = value.get("image", {}).get("format", "dicom")
    image_data_base64 = value.get("image", {}).get("data")
    if not image_data_base64:
        print("No image data.")
        return
    image_bytes = base64.b64decode(image_data_base64)
    if image_format == "dicom":
        file_path = os.path.join(SAVE_DIR, f"dicom_{int(time.time()*1000)}_{image_counter}.dcm")
        try:
            with open(file_path, "wb") as f:
                f.write(image_bytes)
        except Exception as e:
            print("Could not save DICOM:", e)
        dicom_img = pydicom.dcmread(BytesIO(image_bytes))
        image_array = dicom_img.pixel_array
        axis_name = None
        try:
            iop = dicom_img.get((0x0020, 0x0037), None)
            if iop and len(iop.value) == 6:
                row = np.array(iop.value[0:3], dtype=float)
                col = np.array(iop.value[3:6], dtype=float)
                normal = np.cross(row, col)
                ax = int(np.argmax(np.abs(normal)))
                axis_name = {0: "sag", 1: "cor", 2: "tra"}[ax]
        except Exception:
            pass
        pane = image_counter % 2
        side_axis[pane] = axis_name
        image_queue.put((image_array, pane))
        image_counter += 1
    else:
        print("Unsupported image format:", image_format)

def on_message(ws, message):
    try:
        if isinstance(message, bytes):
            return
        data = json.loads(message)
        service = data.get("service")
        response = data.get("response", {})
        value = response.get("value")
        if service == "product/image":
            process_image_data(value)
        else:
            process_image_data(value)
    except Exception as e:
        print("on_message error:", e)

def on_error(ws, error):
    print("WebSocket error:", error)

def on_close(ws, close_status_code, close_msg):
    print(f"WebSocket closed: {close_status_code} {close_msg}")

def on_open(ws):
    print("WebSocket connection opened")

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
        kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE, "ssl_version": ssl.PROTOCOL_TLSv1_2}},
    )
    wst.daemon = True
    wst.start()

def process_image_queue():
    if not image_queue.empty():
        image_array, index = image_queue.get()
        comm.data_signal.emit(image_array, index)

# ------------------------- Main -------------------------
if __name__ == "__main__":
    if not is_server_active():
        print("Exiting due to inactive server.")
        raise SystemExit(1)
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
