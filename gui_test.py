from PyQt6.QtWidgets import QApplication, QLabel
from PyQt6.QtCore import QTimer, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFont
import itertools
import time
from base_gui import TrackingGUIWindow

UPDATE_PERIOD = 0.05  # In seconds
TRANSITION_SECONDS = 2.25
HOLD_SECONDS = 1.5
CASE_SECONDS = TRANSITION_SECONDS + HOLD_SECONDS
BAD_OFFSET_MM = 12.0
START_TIME = time.monotonic()
last_case_index = None

HORIZONTAL_CASES = [
    ("Left", BAD_OFFSET_MM),
    ("Centered", 0.0),
    ("Right", -BAD_OFFSET_MM),
]
VERTICAL_CASES = [
    ("High", BAD_OFFSET_MM),
    ("Centered", 0.0),
    ("Low", -BAD_OFFSET_MM),
]
DEPTH_CASES = [
    ("Not far enough in", -BAD_OFFSET_MM),
    ("Correct depth", 0.0),
    ("Too far in", BAD_OFFSET_MM),
]

CASES = [
    {
        "label": f"{horizontal}; {vertical}; {depth}",
        "sagittal": sagittal,
        "coronal": coronal,
        "transversal": transversal,
    }
    for (horizontal, sagittal), (vertical, coronal), (depth, transversal)
    in itertools.product(HORIZONTAL_CASES, VERTICAL_CASES, DEPTH_CASES)
]


def interpolate(start, end, amount):
    return start + (end - start) * amount

def process_tracking_data():
    global last_case_index
    elapsed = time.monotonic() - START_TIME
    case_number = int(elapsed / CASE_SECONDS)
    case_index = case_number % len(CASES)
    time_in_case = elapsed % CASE_SECONDS
    current_case = CASES[case_index]
    previous_case = CASES[case_index - 1] if case_number > 0 else current_case
    transition_amount = min(time_in_case / TRANSITION_SECONDS, 1.0)

    needle_x = interpolate(
        previous_case["sagittal"], current_case["sagittal"], transition_amount
    )
    needle_y = interpolate(
        previous_case["coronal"], current_case["coronal"], transition_amount
    )
    needle_z = interpolate(
        previous_case["transversal"], current_case["transversal"], transition_amount
    )

    if case_index != last_case_index:
        case_label.setText(
            f"Simulator case {case_index + 1}/{len(CASES)}: {current_case['label']}"
        )
        print(case_label.text())
        last_case_index = case_index

    # Place both simulated coils on the transversal axis so that the
    # extrapolated needle tip lands exactly at the position above.
    comm.data_signal.emit(needle_x, needle_y, needle_z - 10.0, "RX1")
    comm.data_signal.emit(needle_x, needle_y, needle_z - 20.0, "RX2")

class Communicate(QObject):
    # For simplicity, a signal will just be 3 floats: x,y,z coordinates in dcs
    data_signal = pyqtSignal(float, float, float, str)


if __name__ == "__main__":
    app = QApplication([])

    # Create the main GUI window
    window = TrackingGUIWindow()
    window.set_desired({
        "Test Point": {
            "transversal": 0.0,
            "coronal": 0.0,
            "sagittal": 0.0,
        }
    })
    case_label = QLabel(window)
    case_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    case_label.setFont(QFont('Arial', 16))
    case_label.setStyleSheet("background-color: lightblue;")
    label_width = int(window.width() * 0.6)
    case_label.setGeometry(
        int((window.width() - label_width) / 2), 10, label_width, 45
    )
    case_label.show()
    comm = Communicate()
    comm.data_signal.connect(window.update_coil)
    data_timer = QTimer()
    data_timer.setInterval(int(UPDATE_PERIOD*1000))
    data_timer.timeout.connect(process_tracking_data)
    data_timer.start()
    app.exec()
