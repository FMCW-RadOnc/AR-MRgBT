from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, QObject, pyqtSignal
import numpy as np
from base_gui import TrackingGUIWindow

MIN_VAL = -20
MAX_VAL = 20
UPDATE_PERIOD = 0.1 # In seconds

def process_tracking_data():
    for coil in list(window.combobox_needle_set):
        x,y,z = (np.random.rand(3) * (MAX_VAL - MIN_VAL)) + MIN_VAL
        comm.data_signal.emit(x, y, z, coil)
        print(x, y, z, coil)

class Communicate(QObject):
    # For simplicity, a signal will just be 3 floats: x,y,z coordinates in dcs
    data_signal = pyqtSignal(float, float, float, str)


if __name__ == "__main__":
    app = QApplication([])

    # Create the main GUI window
    window = TrackingGUIWindow()
    #window.set_desired(needle_positions)
    comm = Communicate()
    comm.data_signal.connect(window.update_coil)
    data_timer = QTimer()
    data_timer.setInterval(int(UPDATE_PERIOD*1000))
    data_timer.timeout.connect(process_tracking_data)
    data_timer.start()
    app.exec()