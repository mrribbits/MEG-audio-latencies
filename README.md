# OPM-MEG Audio Latency Measurement

Tools to measure and characterize the trigger-to-ear audio latency of an
OPM-MEG stimulus pipeline using a BBTK (Cambridge Research Systems Black
Box ToolKit v3). Compares VPIXX hardware-scheduled audio to
PsychoPy PTB software audio, across both pneumatic-tube earpieces and
room loudspeakers.

## Contents

- `audio_latency_bbtk.py` — PsychoPy script that plays 200 trials of a
  short stimulus (sine, click, or narrow-band noise) with a
  simultaneous pixel-mode trigger to BBTK. Supports two audio paths:
  `vpixx` (DATAPixx3 audio schedule, vsync-locked) or `psychopy` (PTB
  backend, prescheduled to next vsync).
- `analyze_click_latency.py` — analyzer for four BBTK RTL files in a
  2×2 design (audio path × transmission medium). Produces summary
  tables in the console, a full 2×2 analysis figure, a tail-filtered
  variant, and a sharable single-page directives table for
  researchers.


## Software Requirements

- PsychoPy 2026.1+ (for the measurement script)
- pypixxlib (VPIXX)
- numpy, matplotlib (for the analyzer)
- The BBTK Software Suite for recording and exporting RTL
  files

## Hardware Requirements
- A stimulus control PC, DATAPixx3, ProPixx projector (120Hz).
- Audio delivery system such as speakers or SOUNDPixx pneumatic tubes.
- DATAPixx3 DOUT wired to a BBTK TTL input to receive PixelMode triggers.

## Setup

    VPIXX DOUT (Pixel Mode B) --> BBTK digital input channel 1  (pixel_trigger)
    Microphone at earpiece    --> BBTK digital input channel 2  (mic)

Audio source depends on `AUDIO_PATH`:

- `AUDIO_PATH = 'vpixx'`    → VPIXX audio-out → SOUNDPixx amp → tubes / speakers
- `AUDIO_PATH = 'psychopy'` → computer → DAC → FOSI amplifier → tubes / speakers


## Running a measurement session

    python audio_latency_bbtk.py

The startup dialog prompts for `measurement_id`, `audio_path`
(`vpixx` or `psychopy`), and `tone_type` (`sine`, `click`, or
`noise`). Recommended default: 2 kHz `click`, which has the sharpest
onset for BBTK detection.

Each session records 200 trials at 1.8–2.2 s jittered ISI. Duration is
about 7 minutes.

Export each BBTK recording as an RTL file.

## Analyzing

Edit the `INPUT_FILES` dict at the top of `analyze_click_latency.py`
to point to your four RTL files. Set `SPEAKER_TO_MIC_DISTANCE_M` to
your measured chair-to-speaker distance (used to correct for open-air
transit in the speakers baseline). Set `FRAME_MS` to your display's
frame period (8.33 ms for 120 Hz) — this is used
to detect the one-frame VPIXX race tail. Then run:

    python analyze_click_latency.py

## Notes

VPIXX audio playback via `DPxWriteRegCacheAfterVideoSync` has a race
condition with `win.flip()` that causes ~10–15% of trials to fire one
display frame later than the main mode. The analyzer detects this
bimodality and reports both the raw SD (including the tail) and the
main-mode SD (excluding it). Use the main-mode SD as the underlying
hardware precision; the tail is a software artifact separable from
audio-path physics.

