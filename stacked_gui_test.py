# Temporary file only used to test out QStackedWidget

from PyQt6.QtWidgets import (
    QWidget,
    QApplication,
    QMainWindow,
    QComboBox,
    QHBoxLayout,
    QVBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QStackedWidget,
    QGridLayout
)
from PyQt6.QtGui import QPainter, QColor, QColorConstants, QPen, QFont
from PyQt6.QtCore import Qt

app = QApplication([])

window = QWidget()
window.setGeometry(QApplication.primaryScreen().geometry())



f = QFrame()
f.setStyleSheet("background-color: green")
f.setFixedSize(200, 400)

stacked = QStackedWidget()
#stacked.setMaximumWidth(100)

no_desired_data_label = QLabel("No Goal Point Data")
no_desired_data_label.setFont(QFont('Arial', 15))
#no_desired_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
no_desired_data_label.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
no_desired_data_label.setWordWrap(True)
stacked.addWidget(no_desired_data_label)
no_actual_data_label = QLabel("No Coil Data")
no_actual_data_label.setFont(QFont('Arial', 15))
#no_actual_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
no_actual_data_label.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
no_actual_data_label.setWordWrap(True)
stacked.addWidget(no_actual_data_label)
data_label = QLabel(f"Data {"X "*100}")
data_label.setFont(QFont('Arial',15))
#data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
data_label.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
data_label.setWordWrap(True)
stacked.addWidget(data_label)

stacked.setCurrentIndex(2)

layout = QVBoxLayout()
layout.addWidget(stacked)
f.setLayout(layout)

main_layout = QGridLayout()
main_layout.addWidget(f,1,1)
main_layout.setRowStretch(0,1)
main_layout.setRowStretch(1,1)
main_layout.setRowStretch(2,1)
main_layout.setColumnStretch(0,1)
main_layout.setColumnStretch(1,1)
main_layout.setColumnStretch(2,1)

window.setLayout(main_layout)
stacked.show()
window.show()

print(data_label.width(), data_label.height())

app.exec()