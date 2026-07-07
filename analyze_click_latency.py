#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BBTK Click-Latency Analysis  (2x2 design: audio path x transmission)
========================================================================

Analyzes four BBTK RTL files from a factorial audio-latency measurement:

                     |   VPIXX audio    | PsychoPy audio
    -----------------|------------------|------------------
    Earpiece tubes   |  tubes-vpixx     |  tubes-psychopy
    Room speakers    |  speakers-vpixx  |  speakers-psychopy

The 2x2 design lets us isolate:

    * PsychoPy vs. VPIXX software overhead (compare columns within a row)
    * Tube contribution to audio-path latency (compare rows within a col)
    * Whether the software overhead depends on the transmission medium
      (should not, but worth verifying)

Uses the same RTL parser as analyze_bbtk_latency.py but is organized
around the 2x2 factorial structure and applies a mandatory speaker-to-
mic acoustic-transit correction to the tube-contribution estimates
(the raw speakers baseline includes air travel not present in the
tubes condition, which biases the naive tube-contribution estimate
downward -- see prior conversation).


CONFIGURATION
-------------
Edit INPUT_FILES to point to your four RTL files, and set
SPEAKER_TO_MIC_DISTANCE_M to your measured value. Click stimulus is
assumed but this script works with any waveform.


OUTPUTS
-------
- Console: per-condition summary + derived comparisons
- Figure: analysis_figures/click_latency_2x2.png
"""

import os
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec


# =============================================================================
# CONFIGURATION
# =============================================================================

# Four RTL files, keyed by (medium, audio_path) role.
INPUT_FILES = {
    ('tubes',    'vpixx'):    'tubes-click-vpixx.rtl',
    ('tubes',    'psychopy'): 'tubes-click-psychopy.rtl',
    ('speakers', 'vpixx'):    'loudspeakers-click-vpixx.rtl',
    ('speakers', 'psychopy'): 'loudspeakers-click-psychopy.rtl',
}

# Speaker cone to mic diaphragm distance (meters). Precisely measured
# to isolate the speakers-condition acoustic-transit contribution.
SPEAKER_TO_MIC_DISTANCE_M = 2.405   # 240.5 cm

# Speed of sound at typical lab temperature (~20 C).
SPEED_OF_SOUND_M_PER_S = 343.0

# Output figures directory
FIGURES_DIR = 'analysis_figures'


# =============================================================================
# RTL FORMAT CONSTANTS  (matches the sine-latency analyzer)
# =============================================================================

STATE_WIDTH       = 23    # channel-state bits at start of each data line
TIMESTAMP_WIDTH   = 9     # us timestamp at end of each data line
TRIGGER_BIT_INDEX = 9     # position 10 = TTL In 1 = pixel trigger
MIC_BIT_INDEX     = 11    # position 12 = Audio In 1 = mic
MAX_LATENCY_US    = 500_000   # 500 ms upper bound for a valid pair

# --- One-frame VPIXX race-condition detection ---
# The DPxWriteRegCacheAfterVideoSync + win.flip() pattern occasionally
# races such that audio fires one display frame later than the trigger.
# Set this to the stim display's frame period (ms). Used to detect and
# filter the resulting one-frame tail from the SD statistic so the
# reported SD reflects the main-mode hardware precision rather than
# the software timing artifact.
FRAME_MS = 8.33   # 120 Hz refresh (use 16.67 for 60 Hz)


# =============================================================================
# PARSING (shared logic with the sine analyzer)
# =============================================================================

def parse_rtl(filepath):
    """Return a list of {t_us, trigger_high, mic_high} event dicts."""
    events = []
    with open(filepath, 'r') as f:
        lines = f.readlines()

    in_data = False
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line == '[Data]':
            in_data = True
            continue
        if not in_data:
            continue
        if len(line) != STATE_WIDTH + TIMESTAMP_WIDTH:
            continue
        state = line[:STATE_WIDTH]
        try:
            t_us = int(line[STATE_WIDTH:])
        except ValueError:
            continue
        events.append({
            't_us':         t_us,
            'trigger_high': state[TRIGGER_BIT_INDEX] == '1',
            'mic_high':     state[MIC_BIT_INDEX]     == '1',
        })
    return events


def compute_latencies_ms(events):
    """Pair trigger and mic rising edges, return per-trial latencies (ms)."""
    trigger_rising, mic_rising = [], []
    prev_trigger = prev_mic = False
    for ev in events:
        if ev['trigger_high'] and not prev_trigger:
            trigger_rising.append(ev['t_us'])
        if ev['mic_high'] and not prev_mic:
            mic_rising.append(ev['t_us'])
        prev_trigger = ev['trigger_high']
        prev_mic     = ev['mic_high']

    trigger_rising = np.array(trigger_rising, dtype=np.int64)
    mic_rising     = np.array(mic_rising, dtype=np.int64)

    paired = []
    dropped = 0
    mic_idx = 0
    for t_trig in trigger_rising:
        while mic_idx < len(mic_rising) and mic_rising[mic_idx] < t_trig:
            mic_idx += 1
        if mic_idx >= len(mic_rising):
            dropped += len(trigger_rising) - len(paired)
            break
        delta = mic_rising[mic_idx] - t_trig
        if delta <= MAX_LATENCY_US:
            paired.append(delta)
            mic_idx += 1
        else:
            dropped += 1
    return np.array(paired) / 1000.0, dropped


# =============================================================================
# STATS
# =============================================================================

def detect_frame_tail(latencies_ms, frame_ms=FRAME_MS, min_tail_frac=0.05):
    """Detect a one-frame race-condition tail in a latency distribution.

    Looks for a bimodal pattern: a substantial cluster of trials at
    median + ~1 frame, with a clear gap between the main mode and that
    cluster. This is the signature of the DPxWriteRegCacheAfterVideoSync
    + win.flip() race in VPIXX mode.

    Returns
    -------
    filtered : np.ndarray
        Latencies with detected tail trials excluded (or the original
        array if no tail is detected).
    detected : bool
        True if a one-frame tail was detected and filtered.
    n_removed : int
        Count of trials removed by the filter.

    Notes
    -----
    Non-bimodal distributions (like PsychoPy's smooth unimodal spread)
    are unaffected: no tail cluster + no gap = no filter applied.
    """
    if len(latencies_ms) == 0:
        return latencies_ms, False, 0

    median = float(np.median(latencies_ms))

    # Window where a one-frame-late tail would land
    tail_lo = median + 0.5 * frame_ms
    tail_hi = median + 1.5 * frame_ms
    # Window between main mode and tail (should be nearly empty if bimodal)
    gap_lo  = median + 0.25 * frame_ms
    gap_hi  = median + 0.5 * frame_ms

    n_total = len(latencies_ms)
    n_tail  = int(np.sum((latencies_ms >= tail_lo) & (latencies_ms < tail_hi)))
    n_gap   = int(np.sum((latencies_ms >  gap_lo)  & (latencies_ms < gap_hi)))

    # Bimodal criteria:
    #   1. tail cluster contains >= min_tail_frac of trials (default 5%)
    #   2. gap immediately below the tail is nearly empty (< 2%)
    is_bimodal = ((n_tail / n_total) >= min_tail_frac
                  and (n_gap / n_total) < 0.02)

    if not is_bimodal:
        return latencies_ms, False, 0

    # Filter: keep trials in the main mode (below the tail window)
    threshold = tail_lo
    main_mode = latencies_ms[latencies_ms < threshold]
    n_removed = n_total - len(main_mode)
    return main_mode, True, n_removed


def summarize(latencies_ms):
    """Return summary statistics as a dict.

    Includes both raw (all-trial) stats and main-mode stats after
    filtering the one-frame race-condition tail. Median is unaffected
    by the tail either way; SD is inflated by the tail if present, so
    the reported SD ('std_main') uses only main-mode trials.
    """
    if len(latencies_ms) == 0:
        return {'n': 0}

    filtered, tail_detected, n_tail = detect_frame_tail(latencies_ms)

    return {
        'n':             int(len(latencies_ms)),
        'n_main':        int(len(filtered)),
        'n_tail':        int(n_tail),
        'tail_detected': bool(tail_detected),
        'mean':          float(np.mean(latencies_ms)),
        'std':           float(np.std(latencies_ms, ddof=1)),
        # SD on main-mode trials only (excludes one-frame race tail)
        'std_main':      float(np.std(filtered, ddof=1)) if len(filtered) > 1 else 0.0,
        'median':        float(np.median(latencies_ms)),
        'p25':           float(np.percentile(latencies_ms, 25)),
        'p75':           float(np.percentile(latencies_ms, 75)),
        'iqr':           float(np.percentile(latencies_ms, 75)
                                - np.percentile(latencies_ms, 25)),
        'min':           float(np.min(latencies_ms)),
        'max':           float(np.max(latencies_ms)),
    }


# =============================================================================
# LABELS AND COLORS
# =============================================================================

# Display labels for each role key
DISPLAY_LABEL = {
    ('tubes',    'vpixx'):    'VPIXX / tubes',
    ('tubes',    'psychopy'): 'PsychoPy / tubes',
    ('speakers', 'vpixx'):    'VPIXX / speakers',
    ('speakers', 'psychopy'): 'PsychoPy / speakers',
}

COLOR_BY_ROLE = {
    ('tubes',    'vpixx'):    '#1f77b4',   # blue
    ('tubes',    'psychopy'): '#d62728',   # red
    ('speakers', 'vpixx'):    '#2ca02c',   # green
    ('speakers', 'psychopy'): '#ff7f0e',   # orange
}


# =============================================================================
# LOAD ALL DATA
# =============================================================================

def load_all():
    """Parse all four files and return a dict keyed by role tuple."""
    data = {}
    for role, filepath in INPUT_FILES.items():
        if not Path(filepath).exists():
            print(f"WARNING: file not found, skipping: {filepath}")
            continue
        events = parse_rtl(filepath)
        lat_ms, dropped = compute_latencies_ms(events)
        stats = summarize(lat_ms)
        data[role] = {
            'filepath':     filepath,
            'latencies_ms': lat_ms,
            'stats':        stats,
            'dropped':      dropped,
        }
        print(f"{DISPLAY_LABEL[role]:<24s}  "
              f"file={filepath}  "
              f"paired={stats['n']}  dropped={dropped}")
    return data


# =============================================================================
# REPORTING
# =============================================================================

def print_summary_table(data):
    print()
    print("=" * 96)
    print(f"LATENCY SUMMARY  (ms)     [click stimulus, 200 trials per condition]")
    print("=" * 96)
    header = (f"{'Condition':<24} {'N':>4} {'Median':>8} {'SD_main':>8} "
              f"{'SD_all':>8} {'Mean':>8} {'IQR':>7} {'Tail':>7}")
    print(header)
    print("-" * 96)
    for role in INPUT_FILES:
        if role not in data:
            continue
        s = data[role]['stats']
        if s['n'] == 0:
            print(f"{DISPLAY_LABEL[role]:<24} (no data)")
            continue
        tail_note = (f"{s['n_tail']} ({100*s['n_tail']/s['n']:.0f}%)"
                     if s['tail_detected'] else '-')
        print(f"{DISPLAY_LABEL[role]:<24} {s['n']:>4} "
              f"{s['median']:>8.2f} {s['std_main']:>8.2f} "
              f"{s['std']:>8.2f} {s['mean']:>8.2f} "
              f"{s['iqr']:>7.2f} {tail_note:>7}")
    print("=" * 96)
    print("SD_main : SD computed on main-mode trials only (excluding one-frame race tail)")
    print("SD_all  : SD across all trials (inflated when a tail is present)")
    print("Tail    : # of trials in the one-frame late cluster (VPIXX race artifact)")


def print_derived_comparisons(data):
    """Compute and print all four derived latencies in the 2x2 design.

    Uses medians rather than means, because the VPIXX distributions have
    a bimodal one-frame race-condition tail (~13% of trials fire one
    display frame later than the main mode). Median gives the typical
    latency, unaffected by the tail.
    """
    # Convenience accessors -- all median-based to avoid bias from the
    # one-frame VPIXX vsync-race tail.
    def med(role):
        return data[role]['stats']['median']
    def iqr(role):
        return data[role]['stats']['iqr']

    tv = ('tubes',    'vpixx')
    tp = ('tubes',    'psychopy')
    sv = ('speakers', 'vpixx')
    sp = ('speakers', 'psychopy')

    if not all(r in data for r in [tv, tp, sv, sp]):
        print("Not all four conditions loaded; skipping derived comparisons.")
        return

    print()
    print("DERIVED COMPARISONS  (ms, using medians)")
    print("=" * 84)

    # Speaker-to-mic acoustic transit correction
    d      = SPEAKER_TO_MIC_DISTANCE_M
    c      = SPEED_OF_SOUND_M_PER_S
    air_ms = d / c * 1000.0
    print(f"Speaker-to-mic geometry:")
    print(f"    distance      = {d:.3f} m  ({d*100:.1f} cm)")
    print(f"    speed of sound = {c:.1f} m/s (@ ~20 C)")
    print(f"    air transit    = {air_ms:.2f} ms")
    print()

    # (1) PsychoPy backend overhead through tubes
    dm = med(tp) - med(tv)
    print(f"(1) PsychoPy overhead (through tubes):")
    print(f"    median(tubes-psychopy) - median(tubes-vpixx)")
    print(f"    = {med(tp):.2f} - {med(tv):.2f}")
    print(f"    = {dm:.2f} ms")
    print()

    # (2) PsychoPy backend overhead through speakers
    dm = med(sp) - med(sv)
    print(f"(2) PsychoPy overhead (through speakers):")
    print(f"    median(speakers-psychopy) - median(speakers-vpixx)")
    print(f"    = {med(sp):.2f} - {med(sv):.2f}")
    print(f"    = {dm:.2f} ms")
    print(f"    Should match (1); mismatch would indicate the software")
    print(f"    overhead depends on which output device is being used.")
    print()

    # (3) Tube contribution (VPIXX audio, distance-corrected)
    tube_v = med(tv) - (med(sv) - air_ms)
    print(f"(3) Tube acoustic contribution (VPIXX audio):")
    print(f"    median(tubes-vpixx) - (median(speakers-vpixx) - air_transit)")
    print(f"    = {med(tv):.2f} - ({med(sv):.2f} - {air_ms:.2f})")
    print(f"    = {tube_v:.2f} ms")
    print()

    # (4) Tube contribution (PsychoPy audio, distance-corrected)
    tube_p = med(tp) - (med(sp) - air_ms)
    print(f"(4) Tube acoustic contribution (PsychoPy audio):")
    print(f"    median(tubes-psychopy) - (median(speakers-psychopy) - air_transit)")
    print(f"    = {med(tp):.2f} - ({med(sp):.2f} - {air_ms:.2f})")
    print(f"    = {tube_p:.2f} ms")
    print(f"    Should match (3); the tube physics is independent of")
    print(f"    which audio subsystem drives the amp.")
    print()

    # Suggested MMN correction constants for the paradigm
    print("Suggested audio-latency correction constants (typical trial):")
    print(f"    VPIXX + tubes:       {med(tv):.1f} ms")
    print(f"    PsychoPy + tubes:    {med(tp):.1f} ms")
    print(f"    VPIXX + speakers:    {med(sv):.1f} ms  (at {d*100:.1f} cm)")
    print(f"    PsychoPy + speakers: {med(sp):.1f} ms  (at {d*100:.1f} cm)")
    print("=" * 84)


# =============================================================================
# VISUALIZATION
# =============================================================================

def make_figure(data, out_path, filter_tail=False):
    """Build the analysis figure with a 2x2 histogram grid, overlaid
    comparison, and per-trial scatter.

    Parameters
    ----------
    data : dict
        Loaded per-condition data from load_all().
    out_path : str
        PNG path to save.
    filter_tail : bool, default False
        If True, one-frame race-condition tail trials are excluded
        from all plots and from the displayed per-condition statistics.
        Titles/labels then show the plotted N and the SD computed on
        the plotted (main-mode) trials.
    """

    order = [k for k in INPUT_FILES if k in data and data[k]['stats']['n'] > 0]
    if not order:
        print("No data to plot.")
        return

    # Build per-condition plotting arrays and display stats. If
    # filter_tail=True, drop the one-frame race tail from each condition
    # and recompute mean/median/SD on what's left.
    plot_data = {}
    for role in order:
        lat = data[role]['latencies_ms']
        if filter_tail:
            lat, _, _ = detect_frame_tail(lat)
        n = int(len(lat))
        if n == 0:
            continue
        plot_data[role] = {
            'lat':    lat,
            'n':      n,
            'mean':   float(np.mean(lat)),
            'median': float(np.median(lat)),
            'std':    float(np.std(lat, ddof=1)) if n > 1 else 0.0,
        }

    fig = plt.figure(figsize=(15, 13))
    gs = GridSpec(4, 2, figure=fig, hspace=0.55, wspace=0.28,
                   top=0.94, bottom=0.05, left=0.07, right=0.98)

    # Rows 0-1: 2x2 grid of individual histograms
    axes_grid = {
        ('tubes',    'vpixx'):    fig.add_subplot(gs[0, 0]),
        ('tubes',    'psychopy'): fig.add_subplot(gs[0, 1]),
        ('speakers', 'vpixx'):    fig.add_subplot(gs[1, 0]),
        ('speakers', 'psychopy'): fig.add_subplot(gs[1, 1]),
    }

    for role, ax in axes_grid.items():
        if role not in plot_data:
            ax.set_visible(False)
            continue
        pd  = plot_data[role]
        lat = pd['lat']
        c   = COLOR_BY_ROLE[role]

        ax.hist(lat, bins=30, color=c, alpha=0.75,
                edgecolor='white', linewidth=0.6)
        ax.axvline(pd['mean'],   color='black', linewidth=1.5,
                    label=f"mean   = {pd['mean']:.2f} ms")
        ax.axvline(pd['median'], color='black', linewidth=1.5, linestyle='--',
                    label=f"median = {pd['median']:.2f} ms")
        ax.set_xlabel('Latency (ms)')
        ax.set_ylabel('Trials')
        ax.set_title(f"{DISPLAY_LABEL[role]}\n"
                     f"(N plotted = {pd['n']}, SD = {pd['std']:.2f} ms)",
                     fontsize=10)
        ax.legend(fontsize=8, loc='upper right', frameon=True)
        ax.grid(alpha=0.3)

    # Row 2: overlaid histogram of all four conditions
    ax_ov = fig.add_subplot(gs[2, :])
    for role in order:
        if role not in plot_data:
            continue
        pd  = plot_data[role]
        lat = pd['lat']
        c   = COLOR_BY_ROLE[role]
        ax_ov.hist(
            lat, bins=60, alpha=0.55, color=c, edgecolor=c, linewidth=0.6,
            label=(f"{DISPLAY_LABEL[role]}   mean={pd['mean']:.2f}  "
                   f"SD={pd['std']:.2f}  (N plotted={pd['n']})"),
        )
    ax_ov.set_xlabel('Latency (ms)')
    ax_ov.set_ylabel('Trials')
    ax_ov.set_title('Overlaid comparison  (all four conditions)', fontsize=11)
    ax_ov.legend(fontsize=9, loc='upper right', frameon=True)
    ax_ov.grid(alpha=0.3)

    # Row 3: per-trial scatter (drift / stability check)
    # For filtered plots, use consecutive integer positions rather than
    # gappy original trial numbers so the scatter reads cleanly.
    ax_sc = fig.add_subplot(gs[3, :])
    for role in order:
        if role not in plot_data:
            continue
        lat = plot_data[role]['lat']
        c   = COLOR_BY_ROLE[role]
        trials = np.arange(1, len(lat) + 1)
        ax_sc.scatter(trials, lat, s=10, alpha=0.7, color=c,
                       edgecolors='none', label=DISPLAY_LABEL[role])
    ax_sc.set_xlabel('Trial number')
    ax_sc.set_ylabel('Latency (ms)')
    ax_sc.set_title('Per-trial latency  (drift / stability check)', fontsize=11)
    ax_sc.legend(fontsize=9, loc='upper right', frameon=True)
    ax_sc.grid(alpha=0.3)

    suptitle = ('BBTK Click-Latency Analysis  '
                '(2x2: audio path × transmission)')
    if filter_tail:
        suptitle += '  -- one-frame VPIXX race tail excluded'
    fig.suptitle(suptitle, fontsize=13, fontweight='bold')

    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"Figure saved: {out_path}")


def make_directives_figure(data, out_path):
    """Sharable table figure with plain-language audio-latency directives.

    Values are median-based (rather than mean-based) because the VPIXX
    distributions have a bimodal one-frame race-condition tail (~13%
    of trials fire one display frame later than the main mode). Median
    reflects the typical trial's behavior; means are inflated by the
    tail. The rounded whole-ms values displayed in rows B-E are the
    median trigger-to-ear delay a researcher will most often see.
    """
    def med(role): return data[role]['stats']['median']
    def sd_main(role): return data[role]['stats']['std_main']

    tv = ('tubes',    'vpixx')
    tp = ('tubes',    'psychopy')
    sv = ('speakers', 'vpixx')
    sp = ('speakers', 'psychopy')

    if not all(r in data for r in [tv, tp, sv, sp]):
        print("Skipping directives figure (need all 4 conditions).")
        return

    # --- Backend-level main-mode SDs for row A ---
    # Only SDs (not medians) are shown in row A. Precision is medium-
    # independent; averaging the two backend SDs is meaningful. In
    # contrast, the median latency depends heavily on which medium
    # (tubes vs. speakers) -- averaging them would give a nonsense
    # midpoint. Absolute latencies are shown in the per-combination
    # rows B-E, where they correspond to real-world configurations.
    vpixx_sd_ms    = (sd_main(tv) + sd_main(sv)) / 2
    psychopy_sd_ms = (sd_main(tp) + sd_main(sp)) / 2

    # --- Rounded per-combination medians for rows B-E ---
    r_vt = int(round(med(tv)))   # VPIXX + tubes
    r_pt = int(round(med(tp)))   # PsychoPy + tubes
    r_vs = int(round(med(sv)))   # VPIXX + speakers
    r_ps = int(round(med(sp)))   # PsychoPy + speakers

    d_m = SPEAKER_TO_MIC_DISTANCE_M

    # Row definitions: (letter, header, body_lines)
    rows = [
        ('A', 'Choosing your audio backend', [
            'VPIXX audio has a much shorter and more stable onset delay than the',
            'PsychoPy/PTB backend. Use VPIXX when onset timing matters.',
            f'    VPIXX SD ≈ {vpixx_sd_ms:.2f} ms    |    PsychoPy SD ≈ {psychopy_sd_ms:.2f} ms',
        ]),
        ('B', 'VPIXX audio + pneumatic tubes', [
            f'Add  ≈ {r_vt} ms  to your trigger time.',
        ]),
        ('C', 'PsychoPy audio + pneumatic tubes', [
            f'Add  ≈ {r_pt} ms  to your trigger time.',
        ]),
        ('D', 'VPIXX audio + room loudspeakers', [
            f'Add  ≈ {r_vs} ms  to your trigger time.',
            f'(Accounts for chair-to-speaker distance of {d_m:.1f} m.)',
        ]),
        ('E', 'PsychoPy audio + room loudspeakers', [
            f'Add  ≈ {r_ps} ms  to your trigger time.',
            f'(Accounts for chair-to-speaker distance of {d_m:.1f} m.)',
        ]),
    ]

    # -------------------------------------------------------------------
    # Layout
    # -------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(13, 9))
    ax.set_axis_off()
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)

    # Title
    ax.text(50, 96.5, 'Audio Latency Correction Guide',
             ha='center', va='center',
             fontsize=17, fontweight='bold')
    ax.text(50, 92.5,
             '200-trial BBTK measurements per condition '
             '(2 kHz click stimulus)',
             ha='center', va='center',
             fontsize=10, style='italic', color='#666666')

    # Variable row heights based on body-line count so multi-line rows
    # (like A) get enough vertical space without shrinking the others.
    base_h = 8.5    # header + one body line
    line_h = 2.6    # per additional body line
    row_hs = [base_h + line_h * max(0, len(lines) - 1)
              for _, _, lines in rows]
    total_h = sum(row_hs)
    top     = 89
    bottom  = top - total_h
    if bottom < 2:
        # Scale down proportionally if we ran out of room
        scale   = (top - 2) / total_h
        row_hs  = [h * scale for h in row_hs]

    letter_x = 5
    body_x   = 12

    y_pos = top
    for i, (letter, header, lines) in enumerate(rows):
        row_h = row_hs[i]
        y_top = y_pos
        y_bot = y_top - row_h

        # Alternating background
        bg = '#f2f4f7' if i % 2 == 0 else '#ffffff'
        ax.add_patch(plt.Rectangle(
            (2, y_bot + 0.5), 96, row_h - 1,
            facecolor=bg, edgecolor='#d0d5dd', linewidth=0.8,
        ))

        # Letter
        ax.text(letter_x, (y_top + y_bot) / 2, letter,
                 ha='center', va='center',
                 fontsize=22, fontweight='bold', color='#1f5aa8')

        # Header (bold), fixed distance from row top
        header_y = y_top - 2.0
        ax.text(body_x, header_y, header,
                 ha='left', va='center',
                 fontsize=12, fontweight='bold', color='#1a1a1a')

        # Body lines, fixed distance from header
        first_line_y = header_y - 2.6
        for j, line in enumerate(lines):
            ax.text(body_x, first_line_y - j * line_h, line,
                     ha='left', va='center',
                     fontsize=10, color='#333333')

        y_pos = y_bot

    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"Figure saved: {out_path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    data = load_all()
    if not data:
        print("No files loaded. Check INPUT_FILES paths.")
        return

    print_summary_table(data)
    print_derived_comparisons(data)

    os.makedirs(FIGURES_DIR, exist_ok=True)

    out_full = os.path.join(FIGURES_DIR, 'click_latency_2x2.png')
    make_figure(data, out_full, filter_tail=False)

    out_notail = os.path.join(FIGURES_DIR, 'click_latency_2x2_no_tail.png')
    make_figure(data, out_notail, filter_tail=True)

    directives_path = os.path.join(FIGURES_DIR, 'latency_directives.png')
    make_directives_figure(data, directives_path)


if __name__ == '__main__':
    main()
