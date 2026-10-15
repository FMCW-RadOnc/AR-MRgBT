"""Offline bounded local Z repair and isolated X/Y excursion rejection.

Whole original readings are selected without averaging, coordinate replacement,
sorting or resampling. Matches the reviewed DW01/DW02 comparison filter.
"""
import math
from itertools import combinations
from statistics import median

FILTER_DEFAULTS = {
    "max_gap_seconds": 0.5,
    "neighbors_each_side": 3,
    "max_neighbor_time_distance_s": 1.5,
    "z_outlier_floor_mm": 5.0,
    "z_outlier_sigma": 4.5,
    "minimum_supporting_neighbors": 4,
    "reversal_radius_rows": 3,
    "reversal_radius_seconds": 1.5,
    "neighbor_agreement_mm": 2.0,
    "minimum_spike_excursion_mm": 3.0,
    "side_reference_tolerance_mm": 2.0,
    "reference_rows_per_side": 3,
    "maximum_spike_run": 2,
    "minimum_coherent_run": 3,
    "gross_axis_step_mm": 10.0,
    "maximum_run_gap_seconds": 1.0,
}


def validate_filter_settings(options):
    unknown = set(options) - set(FILTER_DEFAULTS)
    if unknown:
        raise ValueError("Unknown pullback filter settings: {}".format(sorted(unknown)))
    settings = dict(FILTER_DEFAULTS, **options)
    for name, value in settings.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("pullback {} must be positive and finite".format(name))
        if isinstance(FILTER_DEFAULTS[name], int) and not isinstance(value, int):
            raise ValueError("pullback {} must be an integer".format(name))
    if not 2 <= settings["minimum_supporting_neighbors"] <= 2*settings["neighbors_each_side"]:
        raise ValueError("Z support must be between 2 and the available neighbor count")
    if settings["minimum_coherent_run"] < 3:
        raise ValueError("X/Y coherent runs require at least three readings")
    return settings

def _local_z_fit(candidate,neighbors,settings):
    pairs=list(combinations(neighbors,2))
    slope=min(0.0,median((b['z']-a['z'])/(b['time']-a['time']) for a,b in pairs))
    prediction=median(n['z']-slope*(n['time']-candidate['time']) for n in neighbors)
    residuals=[abs(n['z']-(prediction+slope*(n['time']-candidate['time']))) for n in neighbors]
    center=median(residuals)
    cutoff=max(settings['z_outlier_floor_mm'],center+settings['z_outlier_sigma']*1.4826*median(abs(r-center) for r in residuals))
    return prediction,cutoff,sum(residual<=cutoff for residual in residuals)

def _best_local_subsequence(window,before,after):
    # Dynamic programming maximizes retained rows within the bounded window.
    best=[]
    for i,row in enumerate(window):
        options=[]
        if before is None or before['z']>row['z']:
            gap=row['time']-before['time'] if before else 0
            options.append(((1,-row['fit_error'],-gap),[row]))
        for j,earlier in enumerate(window[:i]):
            if best[j] is None or earlier['z']<=row['z']:
                continue
            score,path=best[j]
            gap=max(-score[2],row['time']-earlier['time'])
            options.append(((score[0]+1,score[1]-row['fit_error'],-gap),path+[row]))
        best.append(max(options,key=lambda item:item[0]) if options else None)
    choices=[]
    if before is None or after is None or before['z']>after['z']:
        gap=after['time']-before['time'] if before and after else 0
        choices.append(((0,0,-gap),[]))
    for entry in best:
        if entry is None:
            continue
        score,path=entry
        last=path[-1]
        if after is not None and last['z']<=after['z']:
            continue
        gap=max(-score[2],after['time']-last['time']) if after else -score[2]
        choices.append(((score[0],score[1],-gap),path))
    return max(choices,key=lambda item:item[0])[1] if choices else None

def _repair_z_reversals(retained,settings):
    retained=list(retained)
    protected_through=-math.inf
    while True:
        conflict=next((i for i in range(1,len(retained)) if retained[i]['z']>=retained[i-1]['z']),None)
        if conflict is None:
            return retained
        center=retained[conflict]['time']
        radius=settings['reversal_radius_rows']
        start,end=max(0,conflict-radius),min(len(retained),conflict+radius+1)
        # Never enlarge a repair into distant readings or revisit a resolved
        # window. Earlier resolved coordinates cannot be overridden later.
        while start<conflict and (retained[start]['time']<=protected_through or
                                 center-retained[start]['time']>settings['reversal_radius_seconds']):
            start+=1
        while end>conflict+1 and retained[end-1]['time']-center>settings['reversal_radius_seconds']:
            end-=1
        window=retained[start:end]
        before=retained[start-1] if start else None
        # A later boundary is not presumed valid. Check only the fixed past
        # and local candidate rows, then resolve any remaining conflict ahead.
        selected=_best_local_subsequence(window,before,None)
        assert selected is not None
        chosen={r['index'] for r in selected}
        for r in window:
            if r['index'] not in chosen:
                r['status']='removed for local Z reversal'
        protected_through=window[-1]['time']
        retained[start:end]=selected

def _lateral_decisions(records,settings):
    runs=[]
    for row in records:
        if (not runs or row['time']-runs[-1][-1]['time']>settings['maximum_run_gap_seconds'] or
            any(abs(row['point'][axis]-runs[-1][-1]['point'][axis])>settings['gross_axis_step_mm'] for axis in range(2))):
            runs.append([])
        runs[-1].append(row)
    decisions={r['index']:dict(status='retained',checks=[]) for r in records}
    for run in runs:
        if len(run)<settings['minimum_coherent_run']:
            for row in run:
                decisions[row['index']]['status']='rejected: unsupported run after gross jump or long gap'
            continue
        # Evaluate short spikes against immutable data. A coherent transition
        # is retained when the two sides disagree; endpoints are never fitted.
        isolated_spikes=set()
        for size in range(1,settings['maximum_spike_run']+1):
            for start in range(1,len(run)-size):
                end=start+size
                block=run[start:end]
                before,after=run[start-1],run[end]
                if size>1 and ({before['index'],after['index']} & isolated_spikes):
                    continue
                left=run[max(0,start-settings['reference_rows_per_side']):start]
                right=run[end:end+settings['reference_rows_per_side']]
                reference_lines=[r['index'] for r in left+right]
                assert not set(reference_lines)&{r['index'] for r in block}
                bad_axes=[]
                for axis in range(2):
                    a,b=before['point'][axis],after['point'][axis]
                    if abs(a-b)>settings['neighbor_agreement_mm']:
                        continue
                    # Every point in the candidate block must leave and
                    # return, rather than lie along a sustained step or bend.
                    if not all((r['point'][axis]-a)*(r['point'][axis]-b)>0 and
                               min(abs(r['point'][axis]-a),abs(r['point'][axis]-b))>settings['minimum_spike_excursion_mm'] for r in block):
                        continue
                    left_level=median(r['point'][axis] for r in left)
                    right_level=median(r['point'][axis] for r in right)
                    if abs(left_level-right_level)>settings['neighbor_agreement_mm']:
                        continue
                    if all((r['point'][axis]-left_level)*(r['point'][axis]-right_level)>0 and
                           min(abs(r['point'][axis]-left_level),abs(r['point'][axis]-right_level))>settings['side_reference_tolerance_mm'] for r in block):
                        bad_axes.append('XY'[axis])
                if bad_axes:
                    if size==1:
                        isolated_spikes.add(block[0]['index'])
                    for row in block:
                        decisions[row['index']]['status']='rejected: isolated '+','.join(bad_axes)+' excursion and return'
                        decisions[row['index']]['checks'].append(dict(block=[r['index'] for r in block],reference_lines=reference_lines,axes=bad_axes))
    return decisions


def filter_pullback_samples(samples, source_sections=None, **options):
    """Filter one needle on Stop; return original rows and rejection diagnostics.

    source_sections separates actual acquisition blocks, such as needle switches.
    Short receipt gaps do not split a local reference; explicit time limits do.
    A later acquisition block cannot erase rows from an earlier block.
    """
    settings = validate_filter_settings(options)
    samples = list(samples)
    sections = list(source_sections) if source_sections is not None else [0]*len(samples)
    if len(sections) != len(samples):
        raise ValueError("Source section count must match sample count")
    rows, parts = [], []
    for index, (timestamp, coordinates) in enumerate(samples):
        timestamp = float(timestamp)
        point = tuple(float(v) for v in coordinates)
        if len(point) != 3 or not all(math.isfinite(v) for v in (timestamp,)+point):
            raise ValueError("Pullback samples require finite receipt times and XYZ")
        if rows and timestamp <= rows[-1]["time"]:
            raise ValueError("Pullback receipt times must strictly increase")
        if not parts or sections[index] != sections[index-1]:
            parts.append([])
        row = dict(index=index, time=timestamp, point=point, z=point[2],
                   raw_segment=len(parts), status="retained", fit_error=0.0)
        rows.append(row)
        parts[-1].append(row)
    selected = []
    for part in parts:
        radius = settings["neighbors_each_side"]
        for i, row in enumerate(part):
            neighbors = [n for n in part[max(0,i-radius):i]+part[i+1:i+radius+1]
                         if abs(n["time"]-row["time"]) <= settings["max_neighbor_time_distance_s"]]
            if len(neighbors) < settings["minimum_supporting_neighbors"]:
                continue
            prediction, cutoff, support = _local_z_fit(row, neighbors, settings)
            row.update(predicted_z=prediction, cutoff=cutoff, fit_error=abs(row["z"]-prediction),
                       z_reference_indices=[n["index"] for n in neighbors])
            if support >= settings["minimum_supporting_neighbors"] and row["fit_error"] > cutoff:
                row["status"] = "isolated Z outlier"
        accepted = _repair_z_reversals([r for r in part if r["status"] == "retained"], settings)
        for row in part:
            row["z_status"] = {"retained":"accepted", "isolated Z outlier":"outlier",
                               "removed for local Z reversal":"backtracking"}[row["status"]]
        bounded = []
        for row in accepted:
            if selected and row["z"] >= selected[-1]["z"]:
                row.update(z_status="backtracking", status="removed at acquisition boundary")
            else:
                bounded.append(row)
                selected.append(row)
        decisions = _lateral_decisions(bounded, settings)
        for row in bounded:
            decision = decisions[row["index"]]
            row.update(xy_status="passed" if decision["status"] == "retained" else "outlier",
                       xy_checks=decision["checks"], status=decision["status"])
    retained, segment = [], 0
    for row in selected:
        if row["xy_status"] == "outlier":
            continue
        if (not retained or row["raw_segment"] != retained[-1]["raw_segment"] or
                row["time"]-retained[-1]["time"] > settings["max_gap_seconds"]):
            segment += 1
        row.update(segment=segment, sample_kind="zxy_filtered")
        retained.append(row)
    return dict(retained=retained, audit=rows, z_selected=len(selected),
                xy_rejected=sum(r["xy_status"] == "outlier" for r in selected), xy_unchecked=0)
