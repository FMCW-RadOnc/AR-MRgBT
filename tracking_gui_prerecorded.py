"""
Version of tracking_gui.py that instead of using Access-i, uses the raw json messages in the recording folder.
"""
import json
import os
import threading
import time
from queue import Queue
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import QObject, pyqtSignal
from base_gui import TrackingGUIWindow

message_q = Queue()
done = False
SLOW_DOWN_FACTOR = 1.0 # 1.0 is realtime, 10.0 is 10x slower than realtime, 0.1 is 10x faster than realtime
recording = "recording3"

def get_message(file_path):
    m = None
    with open(file_path, 'r') as j:
        m = json.load(j)
    return m

# Should be a separate thread
def imitate_websocket():
    """
    1) Go through each file in recording and get times from "acquisition/time".
    2) Calculate the minimum time. That will be our starting point.
    3) Iterate as follows:
        a) Process the message at the current time
        b) Wait x seconds, where x is the difference between the current message time and the next message time multiplied by the slow down factor.
    """
    q = []
    for path in [os.path.join(recording, x) for x in os.listdir(recording)]:
        m = get_message(path)
        t = float(m["acquisition"]["time"])
        q.append((m,t))
    
    q.sort(key=lambda x : x[1])
    for i in range(len(q)-1):
        curr_m, curr_t = q[i]
        message_q.put(curr_m)
        _, next_t = q[i+1]
        time.sleep((next_t - curr_t)*SLOW_DOWN_FACTOR)
    curr_m, curr_t = q[i]
    message_q.put(curr_m)
    message_q.put("DONE")

def consumer():
    while True:
        m = message_q.get()
        if m == "DONE":
            break
        on_message(m)
        message_q.task_done()
        
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
        print(x,y,z, coil_name)
        comm.data_signal.emit(x, y, z, coil_name)

# Should be analogous to on_message in tracking_gui.py
def on_message(message):
    process_tracking_data(message)

if __name__ == "__main__":
    p = threading.Thread(target=imitate_websocket)
    c = threading.Thread(target=consumer)

    app = QApplication([])
    # Create the main GUI window
    window = TrackingGUIWindow()
    window.load_point_data_from_specified_file("temp_desired.csv")
    
    comm = Communicate()
    comm.data_signal.connect(window.update_coil)

    p.start()
    c.start()
    app.exec()