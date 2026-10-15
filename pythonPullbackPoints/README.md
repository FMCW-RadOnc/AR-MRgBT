# Pullback contours for MIM — version 2.10.1

Import **dist/pythonPullbackPoints.zip** using MIM's Extensions import interface.
The package filename is retained from version 1; the entry point is now
**Import Pullback Contours** in category **Contouring** (author **Alexander Kusek**). Replace the old extension
through MIM's extension manager to avoid running the obsolete point importer.
MIM's Python extension runtime must be configured.

Version 2.10.1 supports five-column exports from the recorder's bounded local Z repair and X/Y excursion filter. Each anchor is an unchanged retained measurement, with its original timestamp. MIM draws a shape-preserving curve through these anchors without a second tracking filter, averaging or global refit. Consecutive retained anchors are connected across timestamp gaps; the old 0.5-second drawing break has been removed. Image-volume exclusions still split drawing sections. Older marked formats retain their explicit sections. The helper is loaded from this package so a running MIM session does not reuse an older copy.

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
existing files. New files contain only `Needle`, `Timestamp`, `X Tracker (mm)`, `Y Tracker (mm)`, and `Z Tracker (mm)`. Coordinates must be finite. Unmarked files whose Z strictly decreases per needle across the complete file are treated as final anchors; no filename pattern or metadata columns are required. The importer cannot infer whether a monotone file was filtered, so use the recorder's exports or the reviewed comparison CSVs. Other unmarked files retain the legacy global fit. A singleton also remains at its original coordinate.

Timestamps do not split five-column paths. Needle changes and missing coordinates within a file still split paths. Use separate recordings for separate withdrawals. Older `filtered_v1` metadata is still validated, including its strict decreasing Z and one-original-sample labels; its explicit sections remain separate.

Earlier `_cleaned.csv` recordings remain supported. Older `grouped_v1` sections
are sorted by Z and exact duplicate depths are combined using coordinate medians.
Older `centerline_v1` files require strictly increasing Z within each section.
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
For unmarked inputs that do not have strictly decreasing Z, all valid in-volume samples estimate **one corrected smooth
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

For **filtered original readings**, the recorder checks geometry and receipt timing during acquisition, then filters on Stop. Local Z checks use up to three neighbors per side within 1.5 seconds, an adaptive 5 mm minimum residual threshold, and four supporting neighbors. Local reversal repair is bounded to three rows per side and 1.5 seconds; already resolved windows cannot be overridden by later data.

X/Y filtering removes isolated one- or two-row excursions that return to a consistent surrounding path. Each axis uses 2 mm before/after agreement, more than 3 mm immediate excursion, and separate side-median support within 2 mm. Sustained transitions remain when the sides disagree. Gross lateral steps over 10 mm or gaps over 1 second split the supporting runs; fewer than three readings is unsupported. Whole rows are removed, with no grouping or averaging. See the main README and `params.txt` for exact rules and configurable defaults. These are the same settings used for the reviewed DW01 (14 readings) and DW02 (32 readings) comparisons.

MIM interpolates X(Z) and Y(Z) through the final anchors with shape-preserving cubic Hermite interpolation and continuous first derivative. Interpolation is only for rasterization: it does not alter or add CSV rows. Timestamp gaps do not break the contour in five-column files. Out-of-volume anchors still split paths, and marked files retain their explicit sections. The importer does not rerun the tracking filter on final anchors.

For **older grouped coordinates**, the same interpolation is applied to the
supplied group estimates. It does not rerun tracking rejection or global fitting.

For **older prepared centerlines**, the extension directly maps and rasterizes
the supplied curve without refitting. For all marked formats, sections are not
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
missing slices. Version 2.10.1 execution, display and RTSTRUCT export/reload in a live
MIM session have not been verified here.

Version 2.1 fixes the noxel coordinate-system error by creating DICOM points directly through `XMimPointFactory.createPoint` in both image and contour spaces, then converting them to noxel coordinates. Reimport the rebuilt ZIP to replace version 2.0.
