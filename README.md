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

Once the needle is correctly placed, press **Tab** or click **Start Pullback** at the top center of the HUD and withdraw the needle. The button changes to **Stop Pullback** while recording. Press **Tab** again or click the button after the needle has been removed. The shortcut works while the HUD is active; holding Tab does not repeatedly toggle recording.

Each Access-i frame is processed at the incoming tracking rate by a dedicated pullback pipeline, independent of the HUD's display filter. Receipt timestamps are captured before the frame is queued to the HUD. Stop recording at the intended sheath exit; the pipeline cannot recognize motion after leaving the sheath. An active pullback is also finalized when the HUD exits.

The pipeline writes `MIMData/<Needle>_pullback.csv` automatically when recording stops. Each row is one unchanged retained tip measurement, with its original receipt timestamp. There is no grouping, averaging, fitted endpoint or CSV resampling. For example, needle `DW02` produces `DW02_pullback.csv`; repeats use `DW02_2_pullback.csv` to preserve existing files. Multiple needles produce separate files. Invalid Windows filename characters become underscores; the original needle name stays inside the CSV. Columns are padded for readability. The only columns are `Needle`, `Timestamp`, `X Tracker (mm)`, `Y Tracker (mm)`, and `Z Tracker (mm)`. No path metadata columns are exported. Samples remain in memory until Stop; an interrupted process loses an unfinished recording. Entirely unsupported recordings produce no CSV. No raw CSV or quality report is written.

During acquisition, finite geometry, increasing receipt times and coil spacing are checked. Unless `expected_coil_separation_mm` is configured, the median of the first seven otherwise valid frame separations per needle provides a baseline; bootstrap frames are checked again at finalization. This assumes rigid RX1/RX2 spacing. Motion is evaluated after Stop using the full recording, rather than a sequential 3D speed gate that can let one bad sample affect later decisions.

On Stop, Z is checked first against up to three earlier and three later readings within 1.5 seconds. The candidate is excluded from its reference. A robust nonincreasing Z/time model uses an adaptive residual threshold with a 5 mm minimum and needs four supporting neighbors. With insufficient reference, the original row remains eligible. Reversals are repaired in bounded windows of up to three rows on either side and within 1.5 seconds, preferring the fewest deletions, then model agreement and time coverage. Resolved windows are protected: distant later readings cannot force those earlier points out. This is a local repair, not a global minimum-deletion guarantee.

X/Y filtering then looks for isolated one- or two-row excursions that return to the surrounding path. Each axis is checked independently. Immediate before/after readings must agree within 2 mm, and every candidate row must lie more than 3 mm beyond both in the same direction. Separate medians of up to three rows on each side must also agree within 2 mm, with candidates more than 2 mm beyond both. A sustained transition is kept when the two sides disagree. Singleton spikes cannot serve as the immediate evidence for rejecting a neighboring block. Whole rows are deleted; references use the unchanged Z-selected coordinates. Runs split at a gap over 1 second or a step over 10 mm in either lateral axis; runs shorter than three readings are rejected as unsupported. Supported run endpoints remain original.

Needle switches separate local-reference blocks; ordinary receipt gaps use the time limits above. Z decreases across the complete recording per needle. MIM connects consecutive retained anchors in each five-column file/needle even when timestamps are more than 0.5 seconds apart. Missing coordinates, needle switches within a file and out-of-volume anchors still split paths. No averaging, point replacement or grouping occurs.

The `pullback` settings in `params.json` control acquisition gates and both rejection stages; see `params.txt`. This mode assumes the sheath's true Z decreases throughout one withdrawal per needle. Local Z repair and lateral rejection can shorten the supported extent; the final point is not an automatically detected sheath exit. Defaults are engineering starting values, not validated measurement tolerances. Real bends can be rejected and sustained tracking errors can remain. The recorder does not read MR pixels or establish alignment with the visible sheath. Prerecorded playback uses receipt timing, so changing playback speed changes the temporal gates.

The tracker-space tip uses `Tip = RX1 + offset * (RX1 - RX2) / |RX1 - RX2|`. The [Python MIM contour importer](pythonPullbackPoints/README.md), version 2.10.1, uses the absolute tracker tip columns and the confirmed mapping `DICOM = (-X, -Y, Z)`, with no target offset. Replace the extension with the rebuilt ZIP to connect decreasing-Z five-column exports across timestamp gaps. MIM draws a shape-preserving cubic X(Z), Y(Z) curve through the original retained anchors, with dense sampling only for rasterization. It does not filter, average, or globally refit those anchors a second time. Image bounds are preserved. Older marked `filtered_v1`, `grouped_v1` and `centerline_v1` files retain their explicit sections. Unmarked files with strictly decreasing Z per needle use anchor interpolation; other unmarked files retain the legacy global fit. The importer cannot distinguish an unfiltered monotone CSV from a final five-column export, so select CSVs produced by the recorder or the reviewed comparison filter. Select only intended CSVs because folder import is nonrecursive and includes all CSVs, including older recordings. The separate continuous coordinate log records HUD-relative distances and is not used by the importer.

Run the recorder, filtering, and MIM checks with `.\.venv\Scripts\python.exe -m unittest discover -s pythonPullbackPoints -p 'test_*.py'`.

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

`coil_coordinates_log.csv` starts fresh each time the HUD runs. It records `Time` (`HH:MM:SS.mmm`) and `Distance to target x (mm)`, `Distance to target y (mm)`, and `Distance to target z (mm)`. Each signed offset is the displayed needle-tip position minus the currently selected target, using the same tracking filter and display median as the HUD. Positive and negative directions follow the HUD coordinate convention. Rows are skipped when the target or tip is unavailable or an offset is non-finite. The separate pullback CSV stores the cleaned tracker-space centerline.
