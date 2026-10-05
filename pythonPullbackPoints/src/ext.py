"""Native MIM connected pullback contour importer."""
import math
import os
import importlib.util
from MIMPython.EntryPoint import mim_extension_entrypoint
from MIMPython.SupportedIOTypes import XMimImage, XMimSession, String

# MIM keeps Python modules alive across extension replacements. Load this ZIP's
# helper explicitly so a previous extracted copy in sys.modules cannot win.
_core_spec = importlib.util.spec_from_file_location(
    "_pullback_contour_core", os.path.join(os.path.dirname(__file__), "pullback_core.py"))
_core = importlib.util.module_from_spec(_core_spec)
_core_spec.loader.exec_module(_core)
read_paths = _core.read_paths
fit_sheath_curve = _core.fit_sheath_curve
interpolate = _core.interpolate
connected_cells = _core.connected_cells


class ContourList:
    java_name = "java.util.List<com.mimvista.external.contouring.XMimContour>"


def import_contours(session, mr_image, csv_paths):
    if str(mr_image.getInfo().getModality()) != "MR":
        raise ValueError("Select the reference MR series")
    if mr_image.getSpace().getDimensionCount() != 3:
        raise ValueError("Select a static 3D MR series")
    paths = read_paths(csv_paths, include_metadata=True)
    factory = session.getPointFactory()
    dicom = factory.getDicomCoordSystem()
    # Filter in the actual selected image grid, never using screenshot bounds.
    prototype = factory.createPoint(mr_image.getSpace(), dicom, [0.0, 0.0, 0.0])
    image_dims = list(mr_image.getSpace().getDataDims())
    filtered_paths = []
    total_skipped = 0
    for source, needle, segments, prepared in paths:
        retained = []
        skipped = 0
        for segment in segments:
            current_segment = []
            for coordinates in segment:
                for i, value in enumerate(coordinates):
                    prototype.setCoord(i, value)
                raw = prototype.toNoxel().toRawDataLocation()
                if any(not 0 <= raw.getCoord(i) < image_dims[i] for i in range(3)):
                    skipped += 1
                    if current_segment:
                        retained.append(current_segment)
                        current_segment = []
                    continue
                current_segment.append(coordinates)
            if current_segment:
                retained.append(current_segment)
        total_skipped += skipped
        session.createLogger().info("{} / {}: retained {} points; excluded {} outside MR.".format(
            source, needle, sum(len(segment) for segment in retained), skipped))
        if retained:
            # Acquisition already fitted these sections. Preserve their shape
            # and gap boundaries rather than applying a second strong fit.
            corrected = retained if prepared else [fit_sheath_curve(retained)]
            filtered_paths.append((source, needle, corrected))
            if prepared:
                session.createLogger().info("{} / {}: prepared centerline; no additional smoothing.".format(source, needle))
    paths = filtered_paths
    existing = {str(c.getInfo().getName()) for c in mr_image.getContours()}
    existing.update(str(c.getInfo().getName()) for c in mr_image.getPointOverlays())
    created = []
    skipped_grid_samples = 0
    try:
        for source, needle, segments in paths:
            base = "PB_{}_{}".format(needle, source)[:58]
            name, suffix = base, 2
            while name in existing:
                name = "{}_{}".format(base, suffix)
                suffix += 1
            existing.add(name)
            contour = mr_image.createNewContour(name)
            created.append(contour)
            data = contour.getData()
            dims = list(data.getDims())
            spacing = list(contour.getNoxelSizeInMm())
            if len(spacing) != 3 or not all(math.isfinite(v) and v > 0 for v in spacing):
                raise ValueError("Invalid contour spacing")
            point = factory.createPoint(contour.getSpace(), dicom, [0.0, 0.0, 0.0])
            cell = data.createNoxelPointI()
            for segment in segments:
                previous = None
                for coordinates in interpolate(segment, min(spacing) / 2):
                    for i, value in enumerate(coordinates):
                        point.setCoord(i, value)
                    raw = point.toNoxel().toRawDataLocation()
                    current = tuple(int(raw.getCoord(i)) for i in range(3))
                    if any(not 0 <= current[i] < dims[i] for i in range(3)):
                        skipped_grid_samples += 1
                        previous = None
                        continue
                    for voxel in connected_cells(previous or current, current):
                        for i, value in enumerate(voxel):
                            cell.setCoord(i, value)
                        data.setValue(cell, True)
                    previous = current
            contour.sanitize()
            if contour.isEmpty():
                contour.delete()
                created.pop()
    except Exception:
        for contour in reversed(created):
            contour.delete()
        raise
    session.createLogger().info("Version 2.7.0: created {} sheath centerline contours; "
                               "raw inputs use a robust cubic spline; prepared centerlines retain their sections; "
                               "excluded {} source points outside MR and {} contour-grid samples. "
                               "DICOM=(-X,-Y,Z), no target offset.".format(
                                   len(created), total_skipped, skipped_grid_samples))
    return created


@mim_extension_entrypoint(
    name="Import Pullback Contours", author="Alexander Kusek", category="Contouring",
    version="2.7.0", outputNames=["Pullback contours"],
    description="Correct tracking jitter into one smooth X/Y centerline per Z depth using (-X,-Y,Z). "
                "CSV paths: semicolon/newline-separated paths or a folder. "
                "Creates thin editable voxel contours per file and needle.")
def run(session: XMimSession, mr_image: XMimImage, csv_paths: String) -> ContourList:
    return import_contours(session, mr_image, csv_paths)
