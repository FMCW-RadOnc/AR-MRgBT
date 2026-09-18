## Normal Instructions

To generate target points that the AR HUD will read, do the following:
- Open MIM
- Open the desired Series
- Create Point Contours wherever you want a target point. Make sure to name them something you can recognize later.
- Click on the Yellow Hat / Workflows button and search for the workflow "FH Proc Inline Create Needle End Points (1/2)".
- Launch the workflow. This should create a csv file that the AR HUD will automatically read. The HUD will only recognize target points made on the same day it was run.

To run the AR HUD, run the following commands in command line:
- Navigate to the project directory via "cd C:\Brachy Code\AR-MRgBT"
- Activate the Python virtual environment via "brachy\Scripts\activate"
- Open "params.json" and confirm all of the parameters are set to acceptable values.
   - Read "params.txt" for an explanation on what each parameter does   
- Run the HUD via "python tracking_gui.py"

The HUD uses a black, reduced-glare headset display. The clock and exit instructions are in the top corners, and the point and filter selectors are in the bottom corners. Press Escape to open the exit-confirmation dialog.

The needle display updates every 100 ms (10 frames per second by default). Each update shows the coordinate-wise median of the complete needle positions received since the previous update. Incoming samples are still processed by the selected tracking filter at their native rate. `One Euro Filter` is selected by default, so the filter is applied first and the display median second.

### Record a needle pullback

Once the needle is correctly placed, click **Start Pullback** at the top center of the HUD and withdraw the needle. The button changes to **Stop Pullback** while recording. Click it after the needle has been removed.

Each complete RX1/RX2 Access-i frame is used immediately at the incoming tracking rate to calculate a needle-tip position. The result is written to a timestamped file in `MIMData` named `MM_DD_YYYY_pullback_HH_MM_SS_microseconds.csv`. An active pullback is also closed safely when the HUD exits.

Each CSV row contains exactly five fields: the currently selected needle, a local time in `HH:MM:SS.mmm` format (for example, `12:01:29.817`, without a date or UTC offset), and the calculated tracker-space X/Y/Z tip coordinates. The recording date remains in the filename. If the selected needle changes during a pullback, subsequent rows use the new selection. The tracker-space tip uses `Tip = RX1 + offset * (RX1 - RX2) / |RX1 - RX2|`. A zero or non-finite RX1/RX2 separation produces a row with blank X/Y/Z coordinates.

The pullback CSV deliberately remains in the Access-i tracker coordinate frame. It is an auditable source file for later rigid registration into DICOM patient coordinates and RTSTRUCT creation; it is not itself a directly importable MIM contour.

## Other Utilities

Besides the normal HUD, there are several other programs that could be useful when developing or troubleshooting.

### Preview the targeting HUD with simulated sensor data

Run `python gui_test.py` to preview the targeting circles without Access-i or MIM data. Move the mouse to control the simulated needle's horizontal and vertical position, and use the scroll wheel to adjust its insertion depth in 0.5 mm steps.

### Record data from the sensors to use it later

To collect sensor data for later, run "python tracking_recorder.py". To change where the data is saved, change line 16 of "tracking_recorder.py" to use a different
folder name. Running this code will not open the HUD, and it will run for 100 seconds or until it is stopped manually.

### Run the HUD using prerecorded data

To run a version of the HUD where instead of using live data, recorded sensor data is used instead, run "python tracking_gui_prerecorded.py". To change which data folder to use,
change line 16 of "tracking_gui_prerecorded.py" to use a different folder name. By default, data should update as quickly as it was recorded. If you instead want to increase or decrease
the playback speed, change line 15 of "tracking_gui_prerecorded.py" to use a different SLOW_DOWN_FACTOR (1.0 is real time, 10.0 is 10x slower than real time, and 0.1 is 10x faster than real time).

## Quick Note on Troubleshooting

If you cannot connect to the sensors, make sure that a persistent route is set in powershell. Use this command:
"route -p add 10.243.146.24 mask 255.255.255.255 192.168.182.1 IF 3"

3 refers to this interface:
3...00 1b 41 0a 0a 20 ......Intel(R) Ethernet Controller (3) I225-V

To check if the route exists run the command "route print".

### Needle-tip distance log

`coil_coordinates_log.csv` starts fresh each time the HUD runs. It records `Time` (`HH:MM:SS.mmm`) and `Distance to target x (mm)`, `Distance to target y (mm)`, and `Distance to target z (mm)`. Each signed offset is the displayed needle-tip position minus the currently selected target, using the same tracking filter and display median as the HUD. Positive and negative directions follow the HUD coordinate convention. Rows are skipped when the target or tip is unavailable or an offset is non-finite. The separate pullback CSV continues to store raw calculated tracker-space tip positions.
