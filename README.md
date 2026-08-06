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

The HUD starts in its normal gray interface. Click **Headset Mode** to switch to a black, reduced-glare display that hides the controls and leaves only the tracking visuals. Press Escape once to return to the normal interface. From the normal interface, Escape retains its original exit-confirmation behavior.

## Other Utilities

Besides the normal HUD, there are several other programs that could be useful when developing or troubleshooting.

### Preview the targeting HUD with simulated sensor data

Run `python gui_test.py` to preview the targeting circles without Access-i or MIM data. The simulator slowly cycles through all 27 combinations of horizontal, vertical, and insertion-depth states, labeling and holding each case so it can be inspected.

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
