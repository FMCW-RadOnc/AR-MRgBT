# Pullback contours for MIM — version 2.8.0

Import **dist/pythonPullbackPoints.zip** using MIM's Extensions import interface.
The package filename is retained from version 1; the entry point is now
**Import Pullback Contours** in category **Contouring** (author **Alexander Kusek**). Replace the old extension
through MIM's extension manager to avoid running the obsolete point importer.
MIM's Python extension runtime must be configured.

Version 2.8.0 recognizes reduced `grouped_v1` CSVs. The recorder produces one
robust coordinate per group of up to four measurements, capped at 10 mm of
travel. MIM draws a smooth shape-preserving cubic curve through those anchors;
the dense points used to paint contour voxels are never written to the CSV.
Separate `Segment` sections are preserved. Existing `centerline_v1` CSVs retain
their no-refit behavior, and unmarked raw CSVs retain the robust global spline
introduced in 2.6.0. The helper is loaded from this extension package so a running
MIM session does not reuse an older copy.

## Run

1. Open the matching static 3D MR image series in MIM.
2. Run **Import Pullback Contours**.
3. Select the MR for `mr_image`.
4. For `csv_paths`, enter full CSV paths separated by semicolons or newlines,
   or enter a folder containing only the intended pullback CSVs. Example:

```text
C:\Pullbacks\needle1.csv;C:\Pullbacks\needle2.csv
```

Hide earlier `PB_...` contours for the same recording when checking the new result.
Each run creates a new contour and keeps existing contours; displaying multiple
imports can show multiple locations on one slice even when each fit is a single path.

The extension reads `Needle`, `X Tracker (mm)`, `Y Tracker (mm)`, and
`Z Tracker (mm)` from each CSV. It uses the absolute calculated **tip** coordinates,
not individual coil coordinates or the distance-to-target columns. Select the
new recorder's `<Needle>_pullback.csv` files in `MIMData`, one per needle.
For example, `DW02_pullback.csv`; repeats use `DW02_2_pullback.csv` to preserve
existing files. Earlier `_cleaned.csv` recordings remain supported. Grouped files
have `Path Type=grouped_v1`, a required `Segment` identifier, and `Samples Used`
for each estimate. Their timestamps identify the estimated position time.
Grouped points must be finite and each section contiguous. The extension sorts
each section by Z and combines exact duplicate depths with coordinate medians.
Older `centerline_v1` files still require strictly increasing Z within a section.
Mixed path types or unknown markers fail validation. Earlier pullbacks with additional distance
columns are also accepted; those extra columns are ignored. Folder imports are
nonrecursive and import every CSV in that folder, including any legacy raw files;
select only the intended cleaned files to avoid displaying duplicate paths.
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
For legacy raw inputs, all valid in-volume samples estimate **one corrected smooth
curved centerline with a single X/Y position at each DICOM Z depth**. Z always
orders the fit, as in version 2.3.1. Raw points are not individually plotted or
connected in acquisition order. Duplicate depths and pullback reversals cannot
produce branches or multiple centerline positions at a depth.

Coordinate medians in 1 mm Z bins reduce jitter and pause-related weighting.
All bin centers are then fitted together with a cubic B-spline. Broad spans and
an integrated squared-curvature penalty suppress small zigzags, while allowing
larger bends with nonuniform curvature. The smoothing length is 20 mm for long
pullbacks, capped at one fifth of the measured Z extent for shorter pullbacks.
Five fit iterations reduce the influence of isolated lateral tracking outliers.
The fitted spline has continuous slope and curvature at its span joins.

The complete minimum-to-maximum measured Z extent is retained; endpoint X/Y
positions follow the corrected fit. The curve is sampled every 0.25 mm or less
along Z, then subdivided for physical contour voxel spacing. Missing measurements,
needle switches, and excluded out-of-volume samples are bridged within the same
file/needle. Separate files and different needle names are never joined.
A single sample or samples at identical Z produce one median position. Very short
or two-depth recordings use straight-line correction because curvature cannot be
estimated reliably. Keep distinct withdrawals in separate files or use distinct
needle names.

For **grouped coordinates**, acquisition validates geometry, timing, coil
separation, and speed. On stop, a sliding median-based motion fit rejects spikes,
then nonoverlapping groups of up to four readings are reduced by rejecting
motion-model residual outliers and averaging the inliers. The 10 mm travel cap
shortens groups during fast withdrawal to avoid averaging across a broad bend.
The first/last groups provide locally fitted endpoints at retained timestamps;
a short final remainder may overlap preceding readings for a stable exit estimate.
A single moving group can provide two endpoints rather than one midpoint.

The extension interpolates X(Z) and Y(Z) through these anchors with PCHIP-style
shape-preserving cubic Hermite interpolation: continuous first derivative,
no additional global smoothing, and no coordinate overshoot between adjacent
anchors. It samples the curve only for contour rasterization. Grouped anchors
remain estimates; small true bends can be lost through averaging, and curvature
between sparse anchors cannot be measured. The CSV itself remains unchanged.

For **older prepared centerlines**, the extension directly maps and rasterizes
the supplied curve without refitting. For both marked formats, sections are not
joined, and out-of-volume source points split sections rather than being bridged.
One file/needle contour may contain disconnected sections at a recording gap or
needle switch.

This assumes one sheath position per Z depth. A sheath that doubles back in Z
cannot be represented by this fit. Smoothing may soften small true bends; sustained
tracking errors can still distort the centerline. Sparse samples cannot recover
an unmeasured bend. The importer uses tracker coordinates; it does not segment
the black sheath or locate its ends from the MR image. Exact centering on the
visible plastic sheath requires an image-derived reference or calibrated
alignment correction; tracking averages alone cannot establish that alignment.
Malformed/non-finite values fail the import. Every file is parsed and its points
checked against the actual selected MR volume before creation. Out-of-volume
points are excluded from a raw-input curve fit and its extent and counted in the log.
Fully excluded paths create no contour. Contour-grid
boundary samples are also skipped and counted. Creation failures roll back the
new contours. Input CSV files remain unchanged.

The result is a **thin connected voxel contour**, suitable for viewing and editing
with MIM's contour tools, not a zero-width vector pen stroke or OPEN_NONPLANAR
DICOM curve. The installed public API exposes editable contour masks, not a 3D
freehand-pen constructor. Samples are interpolated at half the smallest contour
voxel spacing and connected through voxel faces. Width and staircase effects are
set by the contour grid; this is not a measured sheath diameter or a modeled tube.
The apparent line/outline varies with the viewing plane. A continuous curved 3D
contour can appear as separated intersections where it leaves a flat 2D slice.

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
nonuniform bends, sparse jitter and outlier reduction, continuous slope and
curvature at cubic joins, same-Z averaging, reversed recordings, pauses, full
extent, gap bridging, interpolation, voxel connectivity, bounds validation and
rollback with a simulated MIM API. The supplied DW02 recording is also tested on
an oblique anisotropic grid to check one connected spot per axial slice with no
missing slices. Version 2.6 execution, display and RTSTRUCT export/reload in a live
MIM session have not been verified here.

Version 2.1 fixes the noxel coordinate-system error by creating DICOM points directly through `XMimPointFactory.createPoint` in both image and contour spaces, then converting them to noxel coordinates. Reimport the rebuilt ZIP to replace version 2.0.
