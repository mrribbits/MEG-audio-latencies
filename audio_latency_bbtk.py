#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Audio Latency Measurement via BBTK  (VPIXX vs PsychoPy comparison)
========================================================================

PURPOSE
-------
Measure the acoustic transit delay of the OPM-MEG headphone system --
i.e. the time from the software/hardware trigger that starts audio
playback to the moment the sound emerges at the earpiece. This latency
is a constant offset that MMN peak latencies (and any tightly time-
locked auditory analysis) need to be corrected by.

This script supports TWO audio paths, selectable via the AUDIO_PATH
parameter:

    'vpixx'    : audio played by the VPIXX DATAPixx3 audio subsystem
                 (hardware-scheduled, vsync-locked). This is the
                 ground truth for the audio path used by
                 oddball_active_v2_ft_cued.py.

    'psychopy' : audio played by psychopy.sound.Sound with the PTB
                 backend, prescheduled via play(when=nextFlipPTB).
                 This is the audio path used by the two
                 psychopy_audio / pyaud_kbd oddball variants.

Run both, subtract, and you have a quantitative comparison of the
extra latency (and jitter) that PsychoPy PTB introduces over the
VPIXX ground truth.

CAVEAT: the two paths use different hardware to reach the amplifier
(VPIXX DAC vs. computer sound card), so the difference is not purely
"PsychoPy software overhead" -- it is "VPIXX-audio path" vs.
"PsychoPy-audio path" in aggregate. On modern computer sound cards the
DAC contribution is typically well under a ms and the difference is
dominated by PsychoPy's software latency, but that assumption is
worth verifying on your hardware.

SETUP
-----
    VPIXX DOUT (Pixel Mode B) --> BBTK digital input channel 1  (pixel_trigger)
    Microphone at earpiece    --> BBTK digital input channel 2  (mic)

    Audio source (depending on AUDIO_PATH):
      AUDIO_PATH = 'vpixx'    -> VPIXX audio-out cable to amplifier
      AUDIO_PATH = 'psychopy' -> computer sound card cable to amplifier

    The amplifier + pneumatic tubes + earpiece + mic path is the same
    for both audio paths -- only the source cable to the amplifier
    changes. Physically re-wire the amplifier input (or use whatever
    mixer/switcher your lab has) before switching AUDIO_PATH.

Both trigger and mic feed the same BBTK, so their timestamps live on
one clock and their difference is the audio-path latency free of
cross-device clock reconciliation.

Configure the BBTK software (BBTKPy / BBTK Software Suite) for:
    - Channel 1 name: pixel_trigger  (rising edge, TTL)
    - Channel 2 name: mic            (rising edge on sound onset)
    - Sample rate  : as high as your BBTK model supports
    - Recording    : begin recording BEFORE starting this script;
                     stop after the script exits
    - Export       : one row per detected edge, with timestamps

For each trial the BBTK file contains a pair of events:
    pixel_trigger @ t_N
    mic           @ t_N + latency

The distribution of (t_mic - t_pixel_trigger) over 200 trials is the
audio-path latency. Mean = the correction constant to apply in
analysis. SD tells you jitter of the audio path.

RECOMMENDED WORKFLOW
--------------------
    1. Wire up the physical setup (see SETUP above).
    2. Start BBTK recording. Confirm channel names.
    3. Rewire amp input to VPIXX audio output.
       Run this script with AUDIO_PATH='vpixx'. Record the resulting
       BBTK export as, e.g., latency_vpixx_click.csv. Compute mean
       and SD. This is L_vpixx.
    4. Rewire amp input to computer sound-card output.
       Run again with AUDIO_PATH='psychopy'. Same stimulus, same
       trial count. Record as latency_psychopy_click.csv. Compute
       mean and SD. This is L_psychopy.
    5. Extra PsychoPy overhead ~ L_psychopy - L_vpixx.
       Jitter comparison: SD_psychopy vs. SD_vpixx.
    6. Optionally repeat with a different TONE_TYPE (e.g. 'sine' after
       'click') to confirm the numbers are frequency-independent.

WHY THIS DESIGN
---------------
    - No MEG scanner time required; measure any time in the lab.
    - Same-device (BBTK) reference and measurement means no cross-
      device clock skew to correct.
    - BBTK software gives a purpose-built latency histogram/report.
    - Fast iteration when adjusting the audio path.

STIMULUS OPTIONS
----------------
Three tone types are available, selectable via TONE_TYPE:

    'sine'  : 1000 Hz sine, 100 ms, 5 ms cosine on/off ramps.
              Matches the frequency of the paradigm's standard tone.
              Ramp softens the onset transient a little, which slightly
              delays the mic's threshold crossing but is a fair proxy
              for what the paradigm actually plays.

    'click' : 2 kHz tone burst, 10 ms, 0.5 ms cosine ramps at edges.
              Sharp onset -> accurate mic-side onset detection at BBTK.
              The mid-frequency carrier puts the spectral energy where
              tubes transmit and mics respond well; a rectangular click
              has DC-heavy spectrum that neither transmits through
              pneumatic tubing nor gets picked up by small measurement
              mics. Best if you want ground-truth acoustic latency with
              minimal ramp-bias contamination.

    'noise' : 500 Hz-wide band noise burst centered on 1000 Hz,
              100 ms, 5 ms cosine on/off ramps. Excites the tube's
              acoustic response across a range near the paradigm's
              tone frequency. Useful for detecting frequency-dependent
              transit differences (usually negligible for short tubes,
              but worth a quick check).

Recommendation: measure with 'click' for the sharpest reference, then
also run 'sine' to confirm the latency you'll apply to your paradigm's
actual stimuli. Difference should be small (a few hundred us at most).

TIMING (VPIXX mode)
-------------------
Per trial:
    1. Configure the VPIXX audio schedule (once per tone).
    2. DPxStartAudSched (arm on local register).
    3. Set trigger pixel color to TRIGGER_ON.
    4. DPxWriteRegCacheAfterVideoSync (queue push at next vsync).
    5. win.flip() unblocks at the vsync -> audio and MEG trigger edge
       fire together.
    6. Wait for tone_duration.
    7. Set trigger pixel to TRIGGER_RESET, flip.
    8. Wait for jittered ISI (1.8-2.2 s).

TIMING (PsychoPy mode)
----------------------
Per trial:
    1. Set trigger pixel color to TRIGGER_ON.
    2. Preschedule PTB audio via play(when=win.getFutureFlipTime(clock='ptb')).
    3. win.flip() unblocks at the vsync -> MEG trigger edge fires from
       the framebuffer; PTB begins audio playback at (approximately)
       the same instant.
    4. Wait for tone_duration.
    5. Set trigger pixel to TRIGGER_RESET, flip.
    6. Wait for jittered ISI (1.8-2.2 s).

Both modes use DPxWriteRegCacheAfterVideoSync semantics for the
pixel-trigger vsync alignment (in VPIXX mode explicitly; in PsychoPy
mode implicitly via win.flip() blocking on the same vsync).

BACKUP CSV
----------
A per-trial CSV log is written to disk alongside the BBTK file. Its
purpose is to sanity-check trial count, spot any obviously-anomalous
trials at load time, and provide a second view if the BBTK export is
ever ambiguous. Columns:
    trial       - 1..N_TRIALS
    hw_onset    - VPIXX hardware timestamp of the tone vsync (s)
    planned_isi - jittered ISI following this trial (s)
Not used for latency computation -- that comes from the BBTK file.

CONTROLS
--------
    SPACE : begin the measurement (from the "ready" screen)
    ESC   : abort mid-run (writes what's been logged so far)
"""

# =============================================================================
# IMPORTS
# =============================================================================

import os
import sys
import csv

import numpy as np

# Set audio backend preference BEFORE importing psychopy.sound.
# For this measurement we insist on PTB when AUDIO_PATH='psychopy',
# because the whole point is to measure what a PTB-driven paradigm
# will incur. sounddevice is listed as a fallback so the import
# succeeds on machines without psychtoolbox -- but we assert PTB is
# actually loaded before running the PsychoPy-mode measurement.
from psychopy import prefs
prefs.hardware['audioLib'] = ['ptb', 'sounddevice']

from psychopy import visual, sound, core, event, gui, data, logging
from pypixxlib import _libdpx as dp

logging.console.setLevel(logging.CRITICAL)

# Switch to the script folder so relative paths work
script_path = os.path.dirname(sys.argv[0])
if len(script_path) != 0:
    os.chdir(script_path)


# =============================================================================
# EXPERIMENT PARAMETERS
# =============================================================================

# --- Audio path: pick which audio subsystem plays the tone ---
# 'vpixx'    : VPIXX audio schedule (hardware-locked to vsync).
#              Use this to measure the ground-truth tube latency.
# 'psychopy' : psychopy.sound with PTB backend (prescheduled to next vsync).
#              Use this to measure the tube latency + software overhead
#              of the PsychoPy-audio oddball scripts.
AUDIO_PATH = 'vpixx'       # 'vpixx' | 'psychopy'

# --- Stimulus type: pick one ---
# Read the STIMULUS OPTIONS section of the docstring before choosing.
TONE_TYPE = 'sine'         # 'sine' | 'click' | 'noise'

# --- Trial structure ---
N_TRIALS  = 200            # per BBTK measurement session
ISI_MIN   = 1.800          # seconds
ISI_MAX   = 2.200          # seconds

# --- Common audio params ---
AUDIO_SAMPLE_RATE = 48000  # Hz for VPIXX audio codec
AUDIO_AMPLITUDE   = 0.8    # 0-1, scales the peak of the int16 waveform

# --- VPIXX audio output volume ---
# The VPIXX audio codec has its own output-stage volume control,
# separate from the waveform amplitude above. It defaults to 0.0 on
# a freshly-opened device (which produces cleanly-scheduled silent
# playback with no error -- a very hard silence to debug). Set this
# to a value that is comfortably audible at the earpiece.
# Only used when AUDIO_PATH='vpixx'.
VPIXX_AUDIO_VOLUME = 0.5   # 0.0-1.0

# --- PsychoPy audio output volume ---
# psychopy.sound.Sound's own output-stage volume control, applied at
# playback in the PTB backend. Independent of AUDIO_AMPLITUDE (which
# scales the waveform samples themselves) and of the OS master mixer.
# Set this so the earpiece SPL is comparable to what VPIXX_AUDIO_VOLUME
# produces -- both paths should reach the mic at similar loudness for
# a fair BBTK latency comparison.
# Only used when AUDIO_PATH='psychopy'.
PSYCHOPY_AUDIO_VOLUME = 0.5   # 0.0-1.0

# --- 'sine' waveform ---
SINE_FREQ     = 1000       # Hz
SINE_DURATION = 0.100      # seconds
SINE_RAMP     = 0.005      # seconds cosine on/off

# --- 'click' waveform ---
# Short tone burst with sharp cosine on/off ramps. Historically 'click'
# meant a rectangular pulse -- but pure rectangular pulses concentrate
# their spectral energy at low frequencies (peak near DC, first null at
# 1/duration), which pneumatic tubes attenuate heavily and small
# measurement mics don't transmit well. The result at the earpiece is
# an inaudibly soft, hard-to-detect click.
#
# Modulating the burst by a mid-frequency carrier (2 kHz default) moves
# the spectral energy into the band where both tubes and mics respond
# well, without sacrificing the sharp cosine-ramp onset that is the
# whole point of using 'click' for BBTK latency measurement. Onset
# ramp is short (~0.5 ms) to minimize threshold-crossing bias; offset
# ramp prevents a spurious second BBTK event when the burst ends.
CLICK_FREQ     = 2000      # Hz (carrier frequency of the burst)
CLICK_DURATION = 0.010     # seconds
CLICK_RAMP     = 0.0005    # seconds (0.5 ms) cosine on/off

# --- 'noise' waveform ---
NOISE_CENTER_FREQ = 1000   # Hz (centered on paradigm's tone freq)
NOISE_BANDWIDTH   = 500    # Hz total (250 Hz on each side of center)
NOISE_DURATION    = 0.100  # seconds
NOISE_RAMP        = 0.005  # seconds cosine on/off

# --- Trigger pixel (VPIXX Pixel Mode B) ---
TRIGGER_PATCH_SIZE = 1
TRIGGER_ON         = 1     # blue channel value at tone onset
TRIGGER_RESET      = 0     # blue channel value between tones

# --- VPIXX audio buffer address ---
AUDIO_BUFFER_ADDR = int(16.0e6)   # 16,000,000 (VPIXX default)


# =============================================================================
# WAVEFORM GENERATORS
# =============================================================================

def _apply_cosine_ramps(wave, n_ramp):
    """Apply cosine on/off ramps to a waveform in-place. Returns wave."""
    if n_ramp <= 0:
        return wave
    ramp_up   = 0.5 * (1.0 - np.cos(np.pi * np.arange(n_ramp) / n_ramp))
    ramp_down = 0.5 * (1.0 + np.cos(np.pi * np.arange(n_ramp) / n_ramp))
    wave[:n_ramp]  *= ramp_up
    wave[-n_ramp:] *= ramp_down
    return wave


def to_vpixx_int16(wave, amplitude):
    """Scale a float waveform in [-1, +1] to int16 for the VPIXX buffer."""
    wave = np.clip(wave * amplitude, -1.0, 1.0)
    return (wave * 32767.0).astype(np.int16)


def to_psychopy_float32(wave, amplitude):
    """Scale a float waveform in [-1, +1] to float32 for psychopy.sound.Sound."""
    return np.clip(wave * amplitude, -1.0, 1.0).astype(np.float32)


def make_sine(frequency, duration, sample_rate, ramp_duration):
    """Sine tone with cosine on/off ramps. Returns float64 in [-1, +1]."""
    n_samples = int(duration * sample_rate)
    n_ramp    = int(ramp_duration * sample_rate)
    t = np.linspace(0, duration, n_samples, endpoint=False)
    wave = np.sin(2.0 * np.pi * frequency * t)
    wave = _apply_cosine_ramps(wave, n_ramp)
    return wave


def make_click(frequency, duration, sample_rate, ramp_duration):
    """Short tone burst with cosine on/off ramps. Returns float64 in [-1, +1].

    A brief burst of a mid-frequency sine (typically 2 kHz) with sharp
    cosine ramps at each edge. This replaces the naive rectangular
    pulse: rectangular pulses have DC-heavy spectra that pneumatic
    tubes and small mics don't transmit well, giving inaudibly soft
    clicks at the earpiece. A carrier-modulated burst puts the energy
    where the audio path actually responds.

    The onset ramp remains short (~0.5 ms by default) to preserve the
    sharp attack that makes 'click' the best stimulus for BBTK onset
    detection. The offset ramp prevents a spurious second edge at the
    burst's tail.
    """
    n_samples = int(duration * sample_rate)
    n_ramp    = int(ramp_duration * sample_rate)
    t = np.linspace(0, duration, n_samples, endpoint=False)
    wave = np.sin(2.0 * np.pi * frequency * t)
    wave = _apply_cosine_ramps(wave, n_ramp)
    return wave


def make_noise_burst(center_freq, bandwidth, duration, sample_rate,
                     ramp_duration, seed=None):
    """Band-limited noise burst via FFT masking, with cosine on/off ramps.

    Uses numpy's FFT (no scipy dependency). The band is a rectangular
    window in the frequency domain from center - bw/2 to center + bw/2.
    Result is normalized so its peak equals 1. Returns float64.
    """
    n_samples = int(duration * sample_rate)
    n_ramp    = int(ramp_duration * sample_rate)

    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(n_samples)

    # FFT bandpass
    fft   = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate)
    lo    = center_freq - bandwidth / 2.0
    hi    = center_freq + bandwidth / 2.0
    fft[(freqs < lo) | (freqs > hi)] = 0
    wave  = np.fft.irfft(fft, n=n_samples)

    # Normalize peak to 1 so ramps + amplitude behave predictably
    peak = np.max(np.abs(wave))
    if peak > 0:
        wave = wave / peak

    wave = _apply_cosine_ramps(wave, n_ramp)
    return wave


def build_stimulus(tone_type):
    """Dispatch to the requested waveform generator.

    Returns
    -------
    wave : float64 numpy array in [-1, +1], no amplitude applied.
    label : human-readable stimulus description.
    """
    if tone_type == 'sine':
        wave = make_sine(SINE_FREQ, SINE_DURATION, AUDIO_SAMPLE_RATE,
                         SINE_RAMP)
        label = f'sine {SINE_FREQ} Hz, {SINE_DURATION*1000:.0f} ms'
    elif tone_type == 'click':
        wave = make_click(CLICK_FREQ, CLICK_DURATION,
                          AUDIO_SAMPLE_RATE, CLICK_RAMP)
        label = f'click {CLICK_FREQ} Hz burst, {CLICK_DURATION*1000:.1f} ms'
    elif tone_type == 'noise':
        wave = make_noise_burst(NOISE_CENTER_FREQ, NOISE_BANDWIDTH,
                                NOISE_DURATION, AUDIO_SAMPLE_RATE,
                                NOISE_RAMP)
        label = (f'noise burst {NOISE_CENTER_FREQ} Hz ± {NOISE_BANDWIDTH/2:.0f}, '
                 f'{NOISE_DURATION*1000:.0f} ms')
    else:
        raise ValueError(
            f"Unknown TONE_TYPE='{tone_type}'. "
            "Choose one of: 'sine', 'click', 'noise'."
        )
    return wave, label


# =============================================================================
# VPIXX HELPERS
# =============================================================================

def init_vpixx():
    """Open the VPIXX device, enable Pixel Mode B, and init audio codec.

    Also sets the VPIXX audio output volume, which defaults to 0.0 on
    a freshly-connected device -- if you skip this, audio schedules
    play cleanly but silently (with no error), which is a very hard
    silence to debug.
    """
    dp.DPxOpen()
    dp.DPxStopAllScheds()
    dp.DPxEnableDoutPixelModeB()   # blue-channel-only trigger output
    dp.DPxInitAudCodec()           # initialize audio subsystem

    # VPIXX audio output volume. Range 0.0-1.0. Only used when
    # AUDIO_PATH='vpixx'; harmless when using PsychoPy audio (the
    # computer sound card doesn't go through VPIXX).
    dp.DPxSetAudLeftVolume(VPIXX_AUDIO_VOLUME)
    dp.DPxSetAudRightVolume(VPIXX_AUDIO_VOLUME)

    dp.DPxWriteRegCache()


def load_tone_into_buffer(tone_int16, buffer_addr):
    """Push the int16 waveform into DATAPixx3 RAM."""
    dp.DPxWriteAudioBuffer(tone_int16, buffer_addr)
    dp.DPxWriteRegCache()


def prep_tone_schedule(n_samples, buffer_addr):
    """Configure the audio schedule and push config to device.

    Does NOT arm the start bit. Caller must, immediately before
    win.flip(), call:
        dp.DPxStartAudSched()                # arm start bit (local reg)
        dp.DPxWriteRegCacheAfterVideoSync()  # queue push at next vsync
    """
    dp.DPxSetAudioSchedule(0.0, AUDIO_SAMPLE_RATE, n_samples,
                            'mono', buffer_addr)
    dp.DPxWriteRegCache()      # config now on device


def close_vpixx():
    """Cleanly disable pixel mode and disconnect."""
    try:
        dp.DPxDisableDoutPixelMode()
    except Exception:
        pass
    try:
        dp.DPxWriteRegCache()
    except Exception:
        pass
    try:
        dp.DPxClose()
    except Exception:
        pass


# =============================================================================
# COLOR HELPER
# =============================================================================

def rgb_255_to_psychopy(rgb):
    """Convert [R,G,B] in 0-255 to PsychoPy's default [-1,+1] color space."""
    return [(c / 127.5) - 1.0 for c in rgb]


def trigger_color(value):
    """Fill color for the trigger patch. Blue channel = trigger value."""
    return rgb_255_to_psychopy([0, 0, value])


def get_audio_status(tone_stim):
    """Query PTB backend for requested and actual playback start times.

    On the PTB backend, psychtoolbox's audio.Slave exposes a `status`
    dict with:
        RequestedStartTime : the time we asked playback to begin
        StartTime          : the real time playback actually began
    Both are in the PTB clock. Their difference tells us how much later
    than requested audio actually started.

    Returns (requested, actual) as floats in PTB clock, or (None, None)
    on any backend that doesn't expose status (e.g. sounddevice).
    """
    try:
        track = getattr(tone_stim, 'track', None)
        if track is None:
            return None, None
        status = getattr(track, 'status', None)
        if callable(status):
            try:
                status = status()
            except Exception:
                return None, None
        if not isinstance(status, dict):
            return None, None
        requested = status.get('RequestedStartTime',
                               status.get('requestedStartTime'))
        actual    = status.get('StartTime',
                               status.get('startTime'))
        if requested == 0.0:
            requested = None
        if actual == 0.0:
            actual = None
        return requested, actual
    except Exception:
        return None, None


# =============================================================================
# TERMINATE
# =============================================================================

def terminate(win, csv_path, trial_log):
    """Write CSV, close VPIXX, close window, exit.

    CSV columns:
        trial              - trial number (1-based)
        hw_onset           - VPIXX hw clock at the trigger vsync (s)
        planned_isi        - jittered ISI following this trial (s)
        pp_audio_requested - PTB clock: time PsychoPy asked audio to
                             start (empty in VPIXX mode)
        pp_audio_actual    - PTB clock: time PsychoPy reports audio
                             actually started (empty in VPIXX mode)
    """
    try:
        with open(csv_path, 'w', newline='') as f:
            w = csv.DictWriter(
                f,
                fieldnames=['trial', 'hw_onset', 'planned_isi',
                            'pp_audio_requested', 'pp_audio_actual'],
                extrasaction='ignore',
            )
            w.writeheader()
            w.writerows(trial_log)
        print(f"CSV saved: {csv_path}")
    except Exception as e:
        print(f"WARNING writing CSV: {e}")

    close_vpixx()

    if win is not None:
        try:
            win.close()
        except Exception:
            pass

    core.quit()
    sys.exit()


# =============================================================================
# MAIN
# =============================================================================

# --- Session info dialog ---
info = {'measurement_id': '',
        'audio_path':     AUDIO_PATH,
        'tone_type':      TONE_TYPE}
dlg = gui.DlgFromDict(dictionary=info,
                      title='Audio Latency Measurement',
                      order=['measurement_id', 'audio_path', 'tone_type'])
if not dlg.OK:
    core.quit()

AUDIO_PATH = info['audio_path']    # allow override from dialog
TONE_TYPE  = info['tone_type']
if AUDIO_PATH not in ('vpixx', 'psychopy'):
    print(f"ERROR: audio_path must be 'vpixx' or 'psychopy', got '{AUDIO_PATH}'")
    sys.exit(1)
info['date'] = data.getDateStr()

# --- Output CSV path ---
results_folder = 'results_latency'
os.makedirs(results_folder, exist_ok=True)

mid = info['measurement_id'].strip() or 'unnamed'
mid = mid.replace('/', '_').replace(' ', '_')
csv_path = os.path.join(
    results_folder,
    f'audio_latency_{mid}_{AUDIO_PATH}_{TONE_TYPE}_{info["date"]}.csv'
)


# --- VPIXX init ---
init_vpixx()


# --- Build stimulus (float64 in [-1, +1], no amplitude yet) ---
stim_wave_norm, stim_label = build_stimulus(TONE_TYPE)
stim_n_samples = int(len(stim_wave_norm))
tone_dur       = stim_n_samples / AUDIO_SAMPLE_RATE

print(f"Audio path: {AUDIO_PATH}")
print(f"Stimulus:   {stim_label}")
print(f"Duration:   {tone_dur * 1000:.2f} ms "
      f"({stim_n_samples} samples @ {AUDIO_SAMPLE_RATE} Hz)")


# --- Load stimulus into the selected audio subsystem ---
tone_sound = None   # only set in psychopy mode

if AUDIO_PATH == 'vpixx':
    stim_int16 = to_vpixx_int16(stim_wave_norm, AUDIO_AMPLITUDE)
    load_tone_into_buffer(stim_int16, AUDIO_BUFFER_ADDR)
    print(f"Loaded {len(stim_int16)} int16 samples to VPIXX buffer at "
          f"0x{AUDIO_BUFFER_ADDR:X}.")

elif AUDIO_PATH == 'psychopy':
    stim_float32 = to_psychopy_float32(stim_wave_norm, AUDIO_AMPLITUDE)
    tone_sound = sound.Sound(value=stim_float32,
                              sampleRate=AUDIO_SAMPLE_RATE,
                              stereo=False,
                              volume=PSYCHOPY_AUDIO_VOLUME)
    _backend_module = type(tone_sound).__module__
    print(f"PsychoPy sound backend: {_backend_module}")
    if 'backend_ptb' not in _backend_module:
        print("=" * 60)
        print("ERROR: expected PTB audio backend but a different backend")
        print(f"  loaded ({_backend_module}). This measurement requires PTB")
        print("  for precise vsync-locked audio scheduling.")
        print()
        print("  Install psychtoolbox:   pip install psychtoolbox")
        print("  Or set AUDIO_PATH='vpixx' to use VPIXX audio instead.")
        print("=" * 60)
        close_vpixx()
        sys.exit(1)


# --- Precompute jittered ISIs ---
rng  = np.random.default_rng()
isis = rng.uniform(ISI_MIN, ISI_MAX, size=N_TRIALS)

est_min = N_TRIALS * ((ISI_MIN + ISI_MAX) / 2.0) / 60.0
print(f"Estimated total time: ~{est_min:.1f} min "
      f"({N_TRIALS} trials, ISI {ISI_MIN}-{ISI_MAX} s)")


# --- Window (fullscreen on the VPIXX display) ---
win = visual.Window(
    fullscr=True,
    color=[0, 0, 0],
    colorSpace='rgb255',
    units='pix',
    allowGUI=False,
    screen=0,
)
win_w, win_h = win.size


# --- Trigger patch: 1x1 in upper-left corner ---
trigger_x = -win_w / 2.0 + TRIGGER_PATCH_SIZE / 2.0
trigger_y =  win_h / 2.0 - TRIGGER_PATCH_SIZE / 2.0
trigger_patch = visual.Rect(
    win,
    width=TRIGGER_PATCH_SIZE, height=TRIGGER_PATCH_SIZE,
    pos=(trigger_x, trigger_y),
    lineWidth=0,
    fillColor=trigger_color(TRIGGER_RESET),
    fillColorSpace='rgb',
)


# --- Screen text: instructions, progress ---
instr = visual.TextStim(
    win,
    text=(
        "Audio Latency Measurement\n\n"
        f"Audio path     : {AUDIO_PATH}\n"
        f"Stimulus       : {stim_label}\n"
        f"Trials         : {N_TRIALS}\n"
        f"ISI            : {ISI_MIN}-{ISI_MAX} s (jittered)\n\n"
        "Confirm the BBTK is:\n"
        "  - Recording\n"
        "  - Channel 1 wired to VPIXX DOUT (pixel_trigger)\n"
        "  - Channel 2 wired to earpiece mic (mic)\n\n"
        f"Confirm the amplifier input is wired to the {AUDIO_PATH.upper()}\n"
        f"audio output (not the other one).\n\n"
        "Press SPACE to begin measurement.\n"
        "Press ESC to abort at any time."
    ),
    color='white', height=24, wrapWidth=1000,
)
progress = visual.TextStim(
    win, text='', color='white', height=24, pos=(0, 0),
)


# --- Ready screen: wait for experimenter ---
instr.draw()
trigger_patch.fillColor = trigger_color(TRIGGER_RESET)
trigger_patch.draw()
win.flip()
keys = event.waitKeys(keyList=['space', 'escape'])
if 'escape' in keys:
    terminate(win, csv_path, [])


# --- Brief pause with blank + reset trigger so BBTK sees a clean baseline ---
trigger_patch.fillColor = trigger_color(TRIGGER_RESET)
trigger_patch.draw()
win.flip()
core.wait(2.0)


# --- Measurement loop ---
trial_log = []

for trial_num in range(N_TRIALS):

    # Progress readout for the experimenter
    progress.text = f"Trial {trial_num + 1} / {N_TRIALS}"

    if AUDIO_PATH == 'vpixx':
        # 1. Configure the audio schedule and push config to device
        prep_tone_schedule(stim_n_samples, AUDIO_BUFFER_ADDR)

        # 2. Prep visual: trigger patch on + progress text
        progress.draw()
        trigger_patch.fillColor = trigger_color(TRIGGER_ON)
        trigger_patch.draw()

        # 3. Arm audio + queue register push at next vsync
        dp.DPxStartAudSched()
        dp.DPxWriteRegCacheAfterVideoSync()

        # 4. Flip: MEG trigger edge on DOUT and audio playback both fire
        #    at this vsync
        win.flip()
        dp.DPxUpdateRegCache()   # refresh so DPxGetTime returns a fresh sample
        hw_onset = dp.DPxGetTime()

    else:  # AUDIO_PATH == 'psychopy'
        # 1. Prep visual: trigger patch on + progress text
        progress.draw()
        trigger_patch.fillColor = trigger_color(TRIGGER_ON)
        trigger_patch.draw()

        # 2. Preschedule PTB audio to hit the next vsync. On PTB this
        #    achieves sub-ms audio precision: PTB knows the target time
        #    and plans buffer submission around it.
        when_ptb = win.getFutureFlipTime(clock='ptb')
        tone_sound.play(when=when_ptb)

        # 3. Flip: MEG trigger edge on DOUT fires at vsync; PTB starts
        #    audio at (approximately) the same instant.
        win.flip()
        dp.DPxUpdateRegCache()   # refresh so DPxGetTime returns a fresh sample
        hw_onset = dp.DPxGetTime()

    # 5. Wait for tone duration (visual trigger stays high across it)
    core.wait(tone_dur)

    # 5b. In PsychoPy mode, query the audio backend for its own reported
    #     onset times now that playback has definitely started (and
    #     largely finished). Values are in PTB clock. In VPIXX mode
    #     these stay None and land as empty cells in the CSV.
    pp_audio_requested = None
    pp_audio_actual    = None
    if AUDIO_PATH == 'psychopy':
        pp_audio_requested, pp_audio_actual = get_audio_status(tone_sound)

    # 6. Reset trigger to 0 during ISI
    progress.draw()
    trigger_patch.fillColor = trigger_color(TRIGGER_RESET)
    trigger_patch.draw()
    win.flip()

    # 7. Log for CSV
    isi = float(isis[trial_num])
    trial_log.append({
        'trial':              trial_num + 1,
        'hw_onset':           f"{hw_onset:.6f}",
        'planned_isi':        f"{isi:.4f}",
        'pp_audio_requested': f"{pp_audio_requested:.6f}" if pp_audio_requested is not None else '',
        'pp_audio_actual':    f"{pp_audio_actual:.6f}"    if pp_audio_actual    is not None else '',
    })

    # 8. Wait ISI (checking for abort periodically)
    elapsed = 0.0
    step    = 0.100
    while elapsed < isi:
        remaining = min(step, isi - elapsed)
        core.wait(remaining)
        elapsed += remaining
        if event.getKeys(keyList=['escape']):
            print(f"\nAborted at trial {trial_num + 1}.")
            terminate(win, csv_path, trial_log)


# --- Done ---
done = visual.TextStim(
    win,
    text=(
        "Measurement complete.\n\n"
        f"{N_TRIALS} trials logged.\n"
        f"CSV: {os.path.basename(csv_path)}\n\n"
        "Stop the BBTK recording now.\n\n"
        "Press SPACE to exit."
    ),
    color='white', height=28, wrapWidth=1000,
)
done.draw()
trigger_patch.fillColor = trigger_color(TRIGGER_RESET)
trigger_patch.draw()
win.flip()
event.waitKeys(keyList=['space', 'escape'])

print(f"\nCompleted {N_TRIALS} trials.")
print(f"Audio path: {AUDIO_PATH}")
print(f"Stimulus  : {stim_label}")
print(f"CSV path  : {csv_path}")
print("Now analyze the BBTK file to compute latency = "
      "t_mic - t_pixel_trigger for each pair of events.")

terminate(win, csv_path, trial_log)
