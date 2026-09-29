# Pullback contours for MIM — version 2.3.1

Import **dist/pythonPullbackPoints.zip** using MIM's Extensions import interface.
The package filename is retained from version 1; the entry point is now
**Import Pullback Contours** in category **Contouring** (author **Alexander Kusek**). Replace the old extension
through MIM's extension manager to avoid running the obsolete point importer.
MIM's Python extension runtime must be configured.

Version 2.3.1 loads the helper directly from the current extension package. This
fixes launch failures after updating within a running MIM session, where Python
could otherwise reuse the older cached helper without `fit_sheath_line`.

## Run

1. Open the matching static 3D MR image series in MIM.
2. Run **Import Pullback Contours**.
3. Select the MR for `mr_image`.
4. For `csv_paths`, enter full CSV paths separated by semicolons or newlines,
   or enter a folder containing only the intended pullback CSVs. Example:

```text
C:\Pullbacks\needle1.csv;C:\Pullbacks\needle2.csv
```

The extension reads `Needle`, `X Tracker (mm)`, `Y Tracker (mm)`, and
`Z Tracker (mm)` from each CSV. It uses the absolute calculated **tip** coordinates,
not individual coil coordinates or the distance-to-target columns. Future pullbacks contain only needle, time and tracker XYZ. Earlier pullbacks with
additional distance columns are also accepted; those extra columns are ignored.
Distance-only coordinate logs are rejected. No target point or RTSTRUCT is needed.

## Coordinate mapping

```text
DICOM X = -CSV X
DICOM Y = -CSV Y
DICOM Z =  CSV Z
```

This implements the user's confirmed common origin and axis relationship: X points
right, Y anterior, Z superior in Access-i. No translation, target subtraction,
additional registration, or pixel scaling is applied to the physical coordinates.
MIM's API converts DICOM millimeters into the selected contour's own image grid.
Use the MR associated with the recording; these CSVs do not carry a frame UID, so
an in-bounds path alone cannot prove the correct image series was selected.

## Result

One editable native MIM contour is created **per file and needle name**, named
`PB_<needle>_<filename>`. Names get suffixes on repeated imports; existing structures
are preserved. Files are never stitched together even if their needle names match.
All valid in-volume samples for a file/needle are averaged into one straight
centerline by least-squares fitting X and Y against Z. The line preserves the
minimum and maximum measured Z, including extrema inside the recording, while
its endpoint X/Y positions follow the fit. Small jitter, duplicates, reversed
recording order, and brief backward motion do not create zigzags or loops.
Missing samples and needle switches within the same file/needle are bridged.
Keep distinct withdrawals in separate files or use distinct needle names.
This assumes a straight sheath; actual curvature is not retained. Samples have
equal weight, so prolonged pauses and large in-volume outliers can influence the
fit. Z extrema are intentionally retained rather than trimmed as outliers.
A single sample or samples with identical Z produce one averaged point.
Malformed/non-finite values fail the import. Every file is parsed and its points
checked against the actual selected MR volume before creation. Out-of-volume
points are excluded from both the fit and its Z extent and counted in the log.
Fully excluded paths create no contour. Contour-grid
boundary samples are also skipped and counted. Creation failures roll back the
new contours. Input CSV files remain unchanged.

The result is a **thin connected voxel contour**, suitable for viewing and editing
with MIM's contour tools, not a zero-width vector pen stroke or OPEN_NONPLANAR
DICOM curve. The installed public API exposes editable contour masks, not a 3D
freehand-pen constructor. Samples are interpolated at half the smallest contour
voxel spacing and connected through voxel faces. Width and staircase effects are
set by the contour grid; this is not a measured sheath diameter or a modeled tube.
The apparent line/outline varies with the viewing plane.

Inspect the contour on the MR and use **Save RTstruct** to export it. MIM performs
the RTSTRUCT serialization. This extension does not independently write a DICOM
file or automatically save over the loaded structures. Trim recordings to the
intended withdrawal interval; motion after leaving the sheath cannot be recognized
from coordinates alone.

## Build and test

From the repository root:

```powershell
.\.venv\Scripts\python.exe pythonPullbackPoints/build.py
.\.venv\Scripts\python.exe -m unittest discover -s pythonPullbackPoints -p 'test_*.py'
```

The builder uses the real MIM decorator in the installed
`resources/python/py_support.zip` (override path with `--mim-support`). Only project
sources and metadata are packaged. There are no third-party Python dependencies.
API signatures were checked against the installed extension-api.jar, including
createNewContour, getData/setValue, coordinate conversion, and sanitize.
Tests cover absolute-axis mapping, multiple files/needles, invalid gaps,
jitter averaging, full Z extent, gap bridging, interpolation, voxel connectivity, bounds validation and rollback with a simulated
MIM API. Actual execution, display and RTSTRUCT export/reload in a live MIM session
have not been verified here.

Version 2.1 fixes the noxel coordinate-system error by creating DICOM points directly through `XMimPointFactory.createPoint` in both image and contour spaces, then converting them to noxel coordinates. Reimport the rebuilt ZIP to replace version 2.0.
