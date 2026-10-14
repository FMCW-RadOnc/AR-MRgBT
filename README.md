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

The pipeline writes `MIMData/<Needle>_pullback.csv`, containing grouped coordinates for the contour extension, automatically when recording stops. For example, needle `DW02` produces `DW02_pullback.csv`. A recording containing multiple needles produces a separate CSV for each needle. Existing files are preserved by adding a number before `_pullback.csv`, such as `DW02_2_pullback.csv`. Characters that are invalid in Windows filenames are replaced with underscores; the original needle name remains in the CSV. Its first five columns are `Needle`, `Timestamp`, and tracker XYZ, with `Path Type=grouped_v1`, `Segment`, `Sample Kind=robust_group`, and `Samples Used` added. The timestamp represents the group's estimated position time; the coordinate is an estimate derived from its retained measurements. Acquisition samples are held in memory until stop; an interrupted process loses the unfinished recording. An entirely invalid recording produces no CSV. There is no raw CSV or quality report.

During acquisition, finite geometry, increasing receipt times, coil spacing, and tip speed are checked. Unless a measured `expected_coil_separation_mm` is configured, the median separation of the first seven otherwise valid frames for each needle supplies a baseline; bootstrap frames are checked again at finalization. This assumes rigid RX1/RX2 spacing.

On stop, a sliding median-based local motion fit rejects isolated tracking spikes before grouping. Each group then contains up to four consecutive accepted readings, shortened when accumulated physical travel would exceed 10 mm. At a 0.11-second sample interval, four-reading groups normally emit one coordinate per approximately 0.44 seconds; their first-to-last sample span is 0.33 seconds. Within each group, median pairwise coordinate/time slopes and median intercepts estimate local motion. Outliers are identified by their 3D residual from that moving trajectory, using a median absolute deviation threshold. The output coordinate is the mean of the retained measurements, at their mean time. This avoids rejecting normal forward travel as jitter.

The first and last output groups instead use least-squares endpoint estimates from their retained readings at the first/last retained times, preserving the supported withdrawal extent. A short final remainder can overlap preceding readings for a more stable exit estimate, respecting the same four-reading/10 mm limits. One moving group yields two supported endpoints so the contour can represent its length; a single group of identical positions or one reading yields one position. No dense curve points are added to the CSV. A 200 mm pullback sampled 46 times at 0.11-second intervals produces about 16 grouped coordinates under the 10 mm cap, rather than roughly 401 resampled curve points. Gaps longer than 0.5 seconds and needle switches start independent sections, which MIM never joins.

The `pullback` settings in `params.json` control acquisition gates, outlier rejection, group size, and maximum group travel; see `params.txt`. Defaults are engineering starting values, not validated measurement tolerances. Averaging reduces small random fluctuations but cannot distinguish every real bend from motion noise or remove systematic tracking bias. Groups with fewer than three readings cannot independently identify an outlier. The recorder does not read MR pixels: exact alignment to the visible plastic sheath centre requires an image-derived reference or measured alignment correction. Hold the starting position steady briefly and withdraw steadily to increase valid samples per millimeter. Prerecorded playback uses receipt timing, so changing playback speed changes the temporal gates.

The tracker-space tip uses `Tip = RX1 + offset * (RX1 - RX2) / |RX1 - RX2|`. The [Python MIM contour importer](pythonPullbackPoints/README.md), version 2.8.0, uses the absolute tracker tip columns and the confirmed mapping `DICOM = (-X, -Y, Z)`, with no target offset. Import the rebuilt extension ZIP to recognize grouped coordinates. MIM draws a shape-preserving cubic X(Z), Y(Z) curve through the grouped anchors, with dense sampling only for contour rasterization. It does not globally refit these anchors or write points back to the CSV. Exact duplicate depths use coordinate medians, and Z reversals cannot create branches. A true sheath doubling back in Z is still unsupported. Select only the intended `_pullback.csv` files (or earlier `_cleaned.csv` recordings); folder import is nonrecursive and also includes any older raw CSVs still in that folder. Legacy raw and `centerline_v1` files retain their previous import behavior. The separate continuous coordinate log records HUD-relative distances and is not used by the importer.

Run the recorder, grouping, and MIM checks with `.\.venv\Scripts\python.exe -m unittest discover -s pythonPullbackPoints -p 'test_*.py'`.

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
