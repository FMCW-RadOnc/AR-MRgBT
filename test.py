# check_session_id.py
import os
import json
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --------------------------
# Config (override via env)
# --------------------------
REST_HOST = os.getenv("SRC_REST_HOST", "127.0.0.1")     # scanner/console REST host (e.g., 192.168.182.X)
WS_HOST   = os.getenv("SRC_WS_HOST", REST_HOST)         # optional: where WS will be (not used here, printed only)
MRI_SOURCE_IP = os.getenv("SRC_SOURCE_IP", "192.168.182.22")  # your *brachy PC* MRI NIC IP

BASE_URL = f"https://{REST_HOST}:7787/SRC/v2/product"
REQUEST_TIMEOUT = 5  # seconds

# --------------------------
# License block (your current one)
# --------------------------
LICENSE = {
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
}

# --------------------------
# Source-bound HTTPS session (forces REST over MRI NIC; disables proxies)
# --------------------------
from requests.adapters import HTTPAdapter

class SourceBindAdapter(HTTPAdapter):
    def __init__(self, source_ip: str, **kw):
        self._source = (source_ip, 0)  # (IP, ephemeral port)
        super().__init__(**kw)

    def init_poolmanager(self, *args, **kw):
        kw["source_address"] = self._source
        return super().init_poolmanager(*args, **kw)

session = requests.Session()
session.trust_env = False  # ignore system proxy settings
session.mount("https://", SourceBindAdapter(MRI_SOURCE_IP))

PROXIES_OFF = {"http": None, "https": None}

# --------------------------
# Helpers
# --------------------------
def is_server_active() -> bool:
    url = f"{BASE_URL}/remote/getIsActive"
    try:
        r = session.get(url, verify=False, timeout=REQUEST_TIMEOUT, proxies=PROXIES_OFF)
        print("GET  /remote/getIsActive  ->", r.status_code, safe_text(r))
        if r.ok:
            try:
                return r.json().get("value", False)
            except Exception:
                return False
    except requests.RequestException as e:
        print("is_server_active error:", e)
    return False

def get_session_id() -> str | None:
    url  = f"{BASE_URL}/authorization/register"
    body = {"license": LICENSE, "name": "Brachy Session Check"}
    try:
        r = session.post(url, json=body, verify=False, timeout=REQUEST_TIMEOUT, proxies=PROXIES_OFF)
        print("POST /authorization/register ->", r.status_code, safe_text(r))
        if r.ok:
            try:
                return r.json().get("sessionId")
            except Exception:
                return None
    except requests.RequestException as e:
        print("get_session_id error:", e)
    return None

def enable_ws(session_id: str) -> bool:
    url = f"{BASE_URL}/Image/connectServiceToDefaultWebSocket?sessionId={session_id}"
    try:
        r = session.post(url, verify=False, timeout=REQUEST_TIMEOUT, proxies=PROXIES_OFF)
        print("POST /Image/connectServiceToDefaultWebSocket ->", r.status_code, safe_text(r))
        return r.ok
    except requests.RequestException as e:
        print("enable_ws error:", e)
        return False

def safe_text(resp: requests.Response) -> str:
    try:
        t = resp.text
        return t if len(t) < 400 else (t[:400] + " ...[truncated]")
    except Exception:
        return ""

# --------------------------
# Main
# --------------------------
if __name__ == "__main__":
    print("=== check_session_id ===")
    print("REST_HOST      =", REST_HOST)
    print("WS_HOST        =", WS_HOST)
    print("MRI_SOURCE_IP  =", MRI_SOURCE_IP)
    print("BASE_URL       =", BASE_URL)

    active = is_server_active()
    print("active?        =", active)

    sid = get_session_id()
    print("sessionId      =", sid)

    if sid:
        ok = enable_ws(sid)
        print("enable_ws      =", ok)