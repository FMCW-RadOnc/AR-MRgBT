"""CSV validation and target-relative mapping; no MIM/runtime dependencies."""
import csv
import math

DISTANCE_COLUMNS = tuple("Distance to target {} (mm)".format(a) for a in "xyz")
TRACKER_COLUMNS = tuple("{} Tracker (mm)".format(a) for a in "XYZ")


def xyz(values, label):
    try:
        result = tuple(float(v) for v in values)
    except (ValueError, TypeError):
        raise ValueError("{} must contain three numeric millimeter values".format(label))
    if len(result) != 3 or not all(math.isfinite(v) for v in result):
        raise ValueError("{} must contain three finite millimeter values".format(label))
    return result


def read_offsets(path, needle_name, tracker_target=None):
    """Return (source line, timestamp, offset) rows, preserving duplicates/order.

    Blank coordinates represent invalid measurements and are counted, not plotted.
    Malformed numeric data fails the complete import before any points are created.
    """
    if tracker_target is not None:
        tracker_target = xyz(tracker_target, "Tracker target")
    samples, skipped = [], 0
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("CSV is empty")
        reader.fieldnames = [h.strip() for h in reader.fieldnames]
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("CSV contains duplicate column names")
        fields = set(reader.fieldnames)
        if set(DISTANCE_COLUMNS) <= fields:
            columns, mode = DISTANCE_COLUMNS, "distance"
        elif set(TRACKER_COLUMNS) <= fields:
            columns, mode = TRACKER_COLUMNS, "tracker"
            if tracker_target is None:
                raise ValueError("This CSV contains absolute tracker positions, not distances. "
                                 "Supply the target's Access-i X,Y,Z for this recording, "
                                 "or use a new pullback CSV with distance columns.")
        else:
            raise ValueError("CSV must contain the three labeled distance or tracker columns")
        if "Needle" not in fields:
            raise ValueError("Use a pullback CSV with a Needle column, not the continuous "
                             "distance log: the latter cannot identify target changes.")
        if not ({"Timestamp", "Time"} & fields):
            raise ValueError("CSV has no Timestamp or Time column")
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError("CSV row {} has an incorrect number of fields".format(line))
            if row["Needle"].strip() != needle_name:
                continue
            values = [row[c].strip() for c in columns]
            if not all(values):
                skipped += 1
                continue
            offset = xyz(values, "CSV row {}".format(line))
            if mode == "tracker":
                offset = tuple(a - b for a, b in zip(offset, tracker_target))
            samples.append((line, row.get("Timestamp", row.get("Time", "")), offset))
    if not samples:
        raise ValueError("No valid samples for needle {!r}; {} invalid rows".format(needle_name, skipped))
    return samples, skipped


def to_dicom(target, offset):
    tx, ty, tz = xyz(target, "DICOM target")
    dx, dy, dz = xyz(offset, "Offset")
    return tx - dx, ty - dy, tz + dz


def read_paths(csv_paths):
    """Load separate file/needle paths; never join across invalid rows or switches."""
    from pathlib import Path
    paths = []
    for value in str(csv_paths).replace(";", "\n").splitlines():
        value = value.strip().strip('"')
        if not value:
            continue
        path = Path(value)
        paths.extend(sorted(path.glob("*.csv")) if path.is_dir() else [path])
    paths = list(dict.fromkeys(p.resolve() for p in paths))
    if not paths:
        raise ValueError("Provide CSV paths separated by semicolons/newlines, or a CSV folder")
    result = []
    for path in paths:
        groups = {}
        active = None
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise ValueError("Empty CSV: {}".format(path))
            reader.fieldnames = [h.strip() for h in reader.fieldnames]
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError("Duplicate headers: {}".format(path))
            if not set(("Needle",) + TRACKER_COLUMNS) <= set(reader.fieldnames):
                raise ValueError("{} needs Needle and X/Y/Z Tracker (mm). Distance-only CSVs "
                                 "cannot be used as absolute coordinates.".format(path))
            for line, row in enumerate(reader, 2):
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("Malformed row {} in {}".format(line, path))
                needle = row["Needle"].strip()
                if not needle:
                    raise ValueError("Missing needle name at {}:{}".format(path, line))
                segments = groups.setdefault(needle, [])
                values = [row[c].strip() for c in TRACKER_COLUMNS]
                if not all(values):
                    active = None
                    continue
                x, y, z = xyz(values, "{} row {}".format(path.name, line))
                if active != needle:
                    segments.append([])
                segments[-1].append((-x, -y, z))
                active = needle
        for needle, segments in groups.items():
            segments = [segment for segment in segments if segment]
            if not segments:
                raise ValueError("No valid points for {} in {}".format(needle, path))
            result.append((path.stem, needle, segments))
    return result


def fit_sheath_line(segments):
    """Least-squares X(Z), Y(Z) centerline over the full measured Z extent.

    Combine valid samples from one file/needle, including acquisition gaps.
    Sorting/time order and small reversals cannot introduce loops. Endpoint Z
    values are retained; endpoint X/Y are fitted rather than jittery raw tips.
    """
    points = [point for segment in segments for point in segment]
    if not points:
        raise ValueError("Cannot fit a sheath without valid points")
    center = tuple(math.fsum(p[i] for p in points) / len(points) for i in range(3))
    z_min = min(p[2] for p in points)
    z_max = max(p[2] for p in points)
    variance = math.fsum((p[2] - center[2]) ** 2 for p in points)
    if variance == 0:
        return [center]
    slopes = [math.fsum((p[2] - center[2]) * (p[i] - center[i])
                        for p in points) / variance for i in range(2)]
    return [(center[0] + slopes[0] * (z - center[2]),
             center[1] + slopes[1] * (z - center[2]), z)
            for z in (z_min, z_max)]


def interpolate(segment, step_mm):
    """Sample every segment in physical mm, retaining its first/last positions."""
    yield segment[0]
    for a, b in zip(segment, segment[1:]):
        length = math.sqrt(sum((y - x) ** 2 for x, y in zip(a, b)))
        steps = max(1, math.ceil(length / step_mm))
        for i in range(1, steps + 1):
            yield tuple(x + (y - x) * i / steps for x, y in zip(a, b))


def connected_cells(a, b):
    """Join nearby sampled voxel indices through faces, avoiding corner-only joins."""
    current = list(a)
    yield tuple(current)
    for axis in range(3):
        while current[axis] != b[axis]:
            current[axis] += 1 if b[axis] > current[axis] else -1
            yield tuple(current)
