"""CSV validation, coordinate mapping and path sampling; no MIM dependencies."""
import csv
import math
from statistics import median

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


def read_paths(csv_paths, include_metadata=False):
    """Load file/needle samples, marking acquisition gaps for later curve fitting."""
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
        prepared = None
        seen_segments = set()
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
                kind = row.get("Path Type", "").strip()
                if kind not in ("", "centerline_v1"):
                    raise ValueError("Unknown Path Type at {}:{}".format(path, line))
                is_prepared = kind == "centerline_v1"
                if prepared is not None and prepared != is_prepared:
                    raise ValueError("Cannot mix raw and prepared points in {}".format(path))
                prepared = is_prepared
                segment_id = row.get("Segment", "").strip()
                if prepared and not segment_id:
                    raise ValueError("Prepared centerline requires Segment at {}:{}".format(path, line))
                key = (needle, segment_id) if prepared else needle
                values = [row[c].strip() for c in TRACKER_COLUMNS]
                if not all(values):
                    if prepared:
                        raise ValueError("Prepared centerline has missing coordinates")
                    active = None
                    continue
                x, y, z = xyz(values, "{} row {}".format(path.name, line))
                if active != key:
                    if prepared and key in seen_segments:
                        raise ValueError("Prepared Segment must be contiguous")
                    seen_segments.add(key)
                    segments.append([])
                elif prepared and z <= segments[-1][-1][2]:
                    raise ValueError("Prepared centerline depths must strictly increase within Segment")
                segments[-1].append((-x, -y, z))
                active = key
        for needle, segments in groups.items():
            segments = [segment for segment in segments if segment]
            if not segments:
                raise ValueError("No valid points for {} in {}".format(needle, path))
            item = (path.stem, needle, segments)
            result.append(item + (bool(prepared),) if include_metadata else item)
    return result


def _spline_basis(knots, position):
    """Cubic B-spline basis and its first two derivatives on normalized Z."""
    values = [float(a <= position < b or (position == 1 and a < b == 1))
              for a, b in zip(knots, knots[1:])]
    first = [0.0] * len(values)
    second = [0.0] * len(values)
    for degree in range(1, 4):
        next_values, next_first, next_second = [], [], []
        for i in range(len(values) - 1):
            left = knots[i + degree] - knots[i]
            right = knots[i + degree + 1] - knots[i + 1]
            next_values.append(((position - knots[i]) / left * values[i] if left else 0) +
                               ((knots[i + degree + 1] - position) / right * values[i + 1]
                                if right else 0))
            next_first.append((degree / left * values[i] if left else 0) -
                              (degree / right * values[i + 1] if right else 0))
            next_second.append((degree / left * first[i] if left else 0) -
                               (degree / right * first[i + 1] if right else 0))
        values, first, second = next_values, next_first, next_second
    return values, first, second


def _solve_spline(matrix, targets):
    """Solve the small shared X/Y least-squares system with pivoting."""
    count = len(matrix)
    rows = [list(row) + list(target) for row, target in zip(matrix, targets)]
    for column in range(count):
        pivot = max(range(column, count), key=lambda i: abs(rows[i][column]))
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        if abs(divisor) < 1e-14:
            raise ValueError("Sheath curve fit is underdetermined")
        for j in range(column, count + 2):
            rows[column][j] /= divisor
        for i in range(column + 1, count):
            scale = rows[i][column]
            for j in range(column, count + 2):
                rows[i][j] -= scale * rows[column][j]
    coefficients = [[0.0, 0.0] for _ in range(count)]
    for i in reversed(range(count)):
        for coordinate in range(2):
            coefficients[i][coordinate] = rows[i][count + coordinate] - math.fsum(
                rows[i][j] * coefficients[j][coordinate] for j in range(i + 1, count))
    return coefficients


def fit_sheath_curve(segments, smoothing_mm=20.0, step_mm=0.25, bin_mm=1.0):
    """Correct jitter into one smooth X(Z), Y(Z) centerline over the full Z extent.

    Unlike tracing samples or fitting tiny neighborhoods, fit all spatial-bin
    centers together with a coarse cubic B-spline and a curvature penalty.
    Robust reweighting reduces isolated lateral tracking errors. Z is always
    the independent coordinate: acquisition reversals cannot create branches.
    """
    if not all(math.isfinite(v) and v > 0 for v in (smoothing_mm, step_mm, bin_mm)):
        raise ValueError("Curve smoothing and sampling distances must be positive and finite")
    points = [point for segment in segments for point in segment]
    if not points:
        raise ValueError("Cannot fit a sheath without valid points")
    lower, upper = min(p[2] for p in points), max(p[2] for p in points)
    if lower == upper:
        return [tuple(median(p[i] for p in points) for i in range(3))]
    extent = upper - lower
    # Equal spatial weight: a pause must not dominate an entire withdrawal.
    bins = {}
    for point in points:
        bins.setdefault(math.floor((point[2] - lower) / bin_mm), []).append(point)
    centers = [tuple(median(p[i] for p in bins[index]) for i in range(3))
               for index in sorted(bins)]
    if len(centers) == 1:
        by_z = {}
        for point in points:
            by_z.setdefault(point[2], []).append(point)
        centers = [tuple(median(p[i] for p in by_z[z]) for i in range(3))
                   for z in sorted(by_z)]
    steps = max(1, math.ceil(extent / step_mm))
    if len(centers) == 2 or extent < 1.0:
        # With too little depth information, retain the old line correction.
        mean_z = math.fsum(p[2] for p in centers) / len(centers)
        variance = math.fsum((p[2] - mean_z)**2 for p in centers)
        means = [math.fsum(p[i] for p in centers) / len(centers) for i in range(2)]
        slopes = [math.fsum((p[2] - mean_z) * (p[i] - means[i]) for p in centers) /
                  variance for i in range(2)]
        return [(means[0] + slopes[0] * (z - mean_z),
                 means[1] + slopes[1] * (z - mean_z), z)
                for z in (lower + extent * k / steps for k in range(steps + 1))]

    # Broad spans limit spatial wiggles; a penalty also smooths across joins.
    smoothing_length = min(smoothing_mm, extent / 5)
    spans = min(max(1, math.ceil(extent / smoothing_length)), max(1, len(centers) - 3))
    knots = [0.0] * 4 + [i / spans for i in range(1, spans)] + [1.0] * 4
    count = spans + 3
    basis = [_spline_basis(knots, (p[2] - lower) / extent)[0] for p in centers]
    curvature = [[0.0] * count for _ in range(count)]
    # Two-point Gaussian quadrature exactly integrates products of B'' on a span.
    for span in range(spans):
        a, b = span / spans, (span + 1) / spans
        for sign in (-1, 1):
            t = (a + b) / 2 + sign * (b - a) / (2 * math.sqrt(3))
            second = _spline_basis(knots, t)[2]
            for i in range(count):
                for j in range(count):
                    curvature[i][j] += (b - a) / 2 * second[i] * second[j]
    penalty = (smoothing_length / (2 * math.pi * extent))**4
    weights = [1.0] * len(centers)
    coefficients = None
    for iteration in range(5):
        total = math.fsum(weights)
        matrix = [[penalty * value for value in row] for row in curvature]
        targets = [[0.0, 0.0] for _ in range(count)]
        for point, row, weight in zip(centers, basis, weights):
            weight /= total
            for i in range(count):
                for j in range(count):
                    matrix[i][j] += weight * row[i] * row[j]
                for coordinate in range(2):
                    targets[i][coordinate] += weight * row[i] * point[coordinate]
        coefficients = _solve_spline(matrix, targets)
        if iteration == 4:
            break
        residuals = [math.sqrt(sum((math.fsum(b * c[i] for b, c in zip(row, coefficients)) -
                                    point[i])**2 for i in range(2)))
                     for point, row in zip(centers, basis)]
        # Robust radial noise scale; the floor avoids rejecting tiny fit biases.
        cutoff = 4.685 * max(0.25, median(residuals) / 1.1774)
        new_weights = [(1 - (r / cutoff)**2)**2 if r < cutoff else 0.0
                       for r in residuals]
        if sum(w > 0 for w in new_weights) < 2:
            break
        weights = new_weights
    curve = []
    for k in range(steps + 1):
        row = _spline_basis(knots, k / steps)[0]
        curve.append((math.fsum(b * c[0] for b, c in zip(row, coefficients)),
                      math.fsum(b * c[1] for b, c in zip(row, coefficients)),
                      lower + extent * k / steps))
    return curve


def resample_curve(curve, step_mm=0.5):
    """Uniform physical arc-length sampling, preserving both modeled endpoints."""
    if not math.isfinite(step_mm) or step_mm <= 0:
        raise ValueError("Sampling distance must be positive and finite")
    if not curve:
        raise ValueError("Cannot sample an empty curve")
    lengths = [math.sqrt(sum((y - x)**2 for x, y in zip(a, b)))
               for a, b in zip(curve, curve[1:])]
    total = math.fsum(lengths)
    if total == 0:
        return [curve[0]]
    count = max(1, math.ceil(total / step_mm))
    output = [curve[0]]
    index, accumulated = 0, 0.0
    for i in range(1, count):
        distance = total * i / count
        while index < len(lengths) - 1 and accumulated + lengths[index] < distance:
            accumulated += lengths[index]
            index += 1
        fraction = (distance - accumulated) / lengths[index]
        output.append(tuple(x + (y - x) * fraction
                            for x, y in zip(curve[index], curve[index + 1])))
    output.append(curve[-1])
    return output


def interpolate(segment, step_mm):
    """Densely sample the fitted centerline in physical millimeters.

    The adapter uses this after curve fitting to guarantee subvoxel spacing.
    """
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
