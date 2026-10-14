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
    """Load file/needle sections. Metadata adds the path-type string as item four."""
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
        path_type = None
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
                if kind not in ("", "centerline_v1", "grouped_v1"):
                    raise ValueError("Unknown Path Type at {}:{}".format(path, line))
                if path_type is not None and path_type != kind:
                    raise ValueError("Cannot mix path types in {}".format(path))
                path_type = kind
                segment_id = row.get("Segment", "").strip()
                if kind and not segment_id:
                    raise ValueError("Prepared centerline requires Segment at {}:{}".format(path, line))
                key = (needle, segment_id) if kind else needle
                values = [row[c].strip() for c in TRACKER_COLUMNS]
                if not all(values):
                    if kind:
                        raise ValueError("Prepared centerline has missing coordinates")
                    active = None
                    continue
                x, y, z = xyz(values, "{} row {}".format(path.name, line))
                if active != key:
                    if kind and key in seen_segments:
                        raise ValueError("Prepared Segment must be contiguous")
                    seen_segments.add(key)
                    segments.append([])
                elif kind == "centerline_v1" and z <= segments[-1][-1][2]:
                    raise ValueError("Prepared centerline depths must strictly increase within Segment")
                segments[-1].append((-x, -y, z))
                active = key
        for needle, segments in groups.items():
            segments = [segment for segment in segments if segment]
            if not segments:
                raise ValueError("No valid points for {} in {}".format(needle, path))
            item = (path.stem, needle, segments)
            result.append(item + (path_type or "",) if include_metadata else item)
    return result


def estimate_group(samples, outlier_min_mm=2.0, outlier_sigma=4.5):
    """Median-based motion fit rejects spikes; mean of inliers estimates position.

    Samples are (monotonic seconds, XYZ). Testing residuals against the moving
    trajectory avoids treating normal withdrawal progress as noise. Endpoints
    are fitted only at retained timestamps, never extrapolated beyond support.
    """
    if not samples:
        raise ValueError("Cannot estimate an empty group")
    if not all(math.isfinite(v) and v > 0 for v in (outlier_min_mm, outlier_sigma)):
        raise ValueError("Group outlier thresholds must be positive and finite")
    samples = [(float(t), xyz(p, "Group coordinate")) for t, p in samples]
    if any(not math.isfinite(t) for t, _ in samples) or any(b[0] <= a[0] for a, b in zip(samples, samples[1:])):
        raise ValueError("Group times must be finite and strictly increasing")
    reference = samples[len(samples) // 2][0]
    slopes = [median((b[1][axis] - a[1][axis]) / (b[0] - a[0])
                     for i, a in enumerate(samples) for b in samples[i + 1:])
              if len(samples) > 1 else 0.0 for axis in range(3)]
    intercepts = [median(p[axis] - slopes[axis] * (t - reference) for t, p in samples)
                  for axis in range(3)]
    residuals = [math.dist(p, tuple(intercepts[i] + slopes[i] * (t - reference) for i in range(3)))
                 for t, p in samples]
    center = median(residuals)
    scale = 1.4826 * median(abs(r - center) for r in residuals)
    cutoff = max(outlier_min_mm, center + outlier_sigma * scale)
    inliers = [sample for sample, residual in zip(samples, residuals) if residual <= cutoff]
    mean_time = math.fsum(t for t, _ in inliers) / len(inliers)
    mean_point = tuple(math.fsum(p[i] for _, p in inliers) / len(inliers) for i in range(3))
    variance = math.fsum((t - mean_time)**2 for t, _ in inliers)
    fitted_slopes = [math.fsum((t - mean_time) * (p[i] - mean_point[i]) for t, p in inliers) / variance
                     if variance else 0.0 for i in range(3)]
    def at(t):
        return tuple(mean_point[i] + fitted_slopes[i] * (t - mean_time) for i in range(3))
    return {"time": mean_time, "point": mean_point, "samples_used": len(inliers),
            "inlier_times": [t for t, _ in inliers],
            "first": (inliers[0][0], at(inliers[0][0])),
            "last": (inliers[-1][0], at(inliers[-1][0]))}


def reject_motion_outliers(samples, window=5, outlier_min_mm=2.0, outlier_sigma=4.5):
    """Detrended sliding-window rejection before spatial grouping.

    Check each frame against a majority of neighbors. A newest spike cannot
    trigger cascading rejection of earlier good points, as a three-frame gate
    can. Use the first/last full windows at endpoints for equal protection.
    """
    if not isinstance(window, int) or isinstance(window, bool) or window < 3:
        raise ValueError("Outlier window must be an integer >= 3")
    if not samples:
        return []
    size = min(window, len(samples))
    retained, windows = [], {}
    for i, sample in enumerate(samples):
        start = max(0, min(i - size // 2, len(samples) - size))
        if start not in windows:
            estimate = estimate_group(samples[start:start + size], outlier_min_mm, outlier_sigma)
            windows[start] = set(estimate["inlier_times"])
        if sample[0] in windows[start]:
            retained.append(sample)
    return retained


def group_measurements(samples, group_samples=4, max_group_span_mm=10.0,
                       outlier_min_mm=2.0, outlier_sigma=4.5):
    """Reduce accepted frames to group estimates without dense CSV resampling.

    The span is the group's accumulated physical travel, not distance to its
    starting point. The first/last groups represent supported endpoints instead
    of their midpoints, retaining full extent without extra interior anchors.
    """
    if not isinstance(group_samples, int) or isinstance(group_samples, bool) or group_samples < 3:
        raise ValueError("Group sample count must be an integer >= 3")
    if not math.isfinite(max_group_span_mm) or max_group_span_mm <= 0:
        raise ValueError("Group span must be positive and finite")
    samples = list(samples)
    groups, group, travel = [], [], 0.0
    for sample in samples:
        distance = math.dist(group[-1][1], sample[1]) if group else 0.0
        if group and (len(group) >= group_samples or travel + distance > max_group_span_mm):
            groups.append(group)
            group, travel, distance = [], 0.0, 0.0
        group.append(sample)
        travel += distance
    if group:
        groups.append(group)
    estimates = [estimate_group(g, outlier_min_mm, outlier_sigma) for g in groups]
    if not estimates:
        return []
    if len(estimates) == 1:
        estimate = estimates[0]
        if estimate["samples_used"] > 1 and math.dist(estimate["first"][1], estimate["last"][1]) > 1e-6:
            return [dict(estimate, time=t, point=p) for t, p in (estimate["first"], estimate["last"])]
    else:
        # A short final remainder must not leave the exit coordinate depending
        # on a single jittery frame. Overlap preceding support only for this
        # endpoint, respecting the same sample/travel limits and row count.
        support, travel = [], 0.0
        for sample in reversed(samples):
            distance = math.dist(support[-1][1], sample[1]) if support else 0.0
            if support and (len(support) >= group_samples or travel + distance > max_group_span_mm):
                break
            support.append(sample)
            travel += distance
        estimates[-1] = estimate_group(list(reversed(support)), outlier_min_mm, outlier_sigma)
    estimates[0]["time"], estimates[0]["point"] = estimates[0]["first"]
    estimates[-1]["time"], estimates[-1]["point"] = estimates[-1]["last"]
    return estimates


def _pchip_slopes(depths, values):
    lengths = [b - a for a, b in zip(depths, depths[1:])]
    secants = [(b - a) / h for a, b, h in zip(values, values[1:], lengths)]
    if len(values) == 2:
        return [secants[0], secants[0]]
    derivatives = [0.0] * len(values)
    for i in range(1, len(values) - 1):
        a, b = secants[i - 1:i + 1]
        if a * b > 0:
            w1, w2 = 2 * lengths[i] + lengths[i - 1], lengths[i] + 2 * lengths[i - 1]
            derivatives[i] = (w1 + w2) / (w1 / a + w2 / b)
    def endpoint(h0, h1, d0, d1):
        slope = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if slope * d0 <= 0:
            return 0.0
        if d0 * d1 <= 0 and abs(slope) > 3 * abs(d0):
            return 3 * d0
        return slope
    derivatives[0] = endpoint(lengths[0], lengths[1], secants[0], secants[1])
    derivatives[-1] = endpoint(lengths[-1], lengths[-2], secants[-1], secants[-2])
    return derivatives


def curve_through_groups(points, step_mm=0.25):
    """Shape-preserving X(Z), Y(Z) interpolation for contour drawing only.

    Pass through grouped anchors without a second global smoothing fit. Exact
    duplicate depths collapse to one coordinate median; sections are handled
    separately by the caller. No sampled points are written back into the CSV.
    """
    if not math.isfinite(step_mm) or step_mm <= 0:
        raise ValueError("Curve step must be positive and finite")
    by_depth = {}
    for p in points:
        p = xyz(p, "Grouped anchor")
        by_depth.setdefault(p[2], []).append(p)
    if not by_depth:
        raise ValueError("No grouped anchors")
    anchors = [tuple(median(p[i] for p in by_depth[z]) for i in range(3)) for z in sorted(by_depth)]
    if len(anchors) == 1:
        return anchors
    depths = [p[2] for p in anchors]
    slopes = [_pchip_slopes(depths, [p[i] for p in anchors]) for i in range(2)]
    curve = [anchors[0]]
    for j, (a, b) in enumerate(zip(anchors, anchors[1:])):
        h = b[2] - a[2]
        count = max(1, math.ceil(h / step_mm))
        for k in range(1, count):
            t = k / count
            h00, h10, h01, h11 = 2*t**3 - 3*t*t + 1, t**3 - 2*t*t + t, -2*t**3 + 3*t*t, t**3 - t*t
            curve.append(tuple(h00*a[i] + h10*h*slopes[i][j] + h01*b[i] + h11*h*slopes[i][j + 1]
                               for i in range(2)) + (a[2] + h*t,))
        curve.append(b)
    return curve


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
