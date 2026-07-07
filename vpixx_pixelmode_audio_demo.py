"""Minimal VPIXX demo: fire a Pixel-Mode-B trigger byte and start audio
playback simultaneously, locked to one display vsync.

The final win.flip() triggers three events at the same vsync:
    1. The framebuffer pixel at (0,0) is displayed. VPIXX reads its
       blue-channel value and emits that byte on DOUT.
    2. DPxWriteRegCacheAfterVideoSync pushes the armed audio-start bit
       to the device -> hardware audio playback begins.
    3. PsychoPy's back buffer is swapped to the front.
"""

import numpy as np
from scipy.io import wavfile
from psychopy import visual, core, event
from pypixxlib import _libdpx as dp

WAV_PATH          = 'sound.wav'
RESET_VALUE       = 0            # 0-255, baseline blue value between events
TRIGGER_VALUE     = 2            # 0-255, blue-channel value
AUDIO_BUFFER_ADDR = int(16e6)    # where in VPIXX RAM to store the samples

# --- Load WAV -> mono int16 (the format the VPIXX audio buffer expects) ---
sample_rate, audio = wavfile.read(WAV_PATH)
if audio.ndim > 1:
    audio = audio[:, 0]                            # if stereo, take left channel
if np.issubdtype(audio.dtype, np.floating):
    audio = (audio * 32767).astype(np.int16)
elif audio.dtype != np.int16:
    audio = audio.astype(np.int16)

# --- VPIXX setup ---
dp.DPxOpen()
dp.DPxStopAllScheds()
dp.DPxEnableDoutPixelModeB()                       # pixel (0,0) blue -> DOUT byte
dp.DPxInitAudCodec()
dp.DPxSetAudLeftVolume(0.5)                        # defaults are 0.0 -> silence
dp.DPxSetAudRightVolume(0.5)
dp.DPxWriteAudioBuffer(audio, AUDIO_BUFFER_ADDR)   # samples -> VPIXX RAM
dp.DPxSetAudioSchedule(
    0.0,                # onset delay after arm (0 = start immediately when armed)
    sample_rate,        # samples per second
    len(audio),         # total samples to play
    'mono',             # single-channel output
    AUDIO_BUFFER_ADDR,  # RAM address to read samples from
)
dp.DPxWriteRegCache()                              # push schedule config to device

# --- Window and trigger pixel (must land on framebuffer coord (0,0)) ---
win = visual.Window(fullscr=True, color='black', screen=0, units='pix')
w, h = win.size
trigger_patch = visual.Rect(
    win, width=1, height=1,
    pos=(-w/2 + 0.5, h/2 - 0.5),                   # center of the (0,0) pixel
    lineWidth=0,
    fillColorSpace='rgb255',                       # accepts 0-255 per channel
)

# --- Establish baseline: DOUT byte = RESET_VALUE ---
trigger_patch.fillColor = (0, 0, RESET_VALUE)
trigger_patch.draw()
win.flip()
core.wait(0.5)   # 500 ms of clean baseline before firing

# --- Fire trigger + audio, both aligned to the same vsync ---
trigger_patch.fillColor = (0, 0, TRIGGER_VALUE)
trigger_patch.draw()
dp.DPxStartAudSched()                              # arm audio locally
dp.DPxWriteRegCacheAfterVideoSync()                # queue push at next vsync
win.flip()                                         # blocks until that vsync

# --- Wait for audio to finish, then return trigger to baseline ---
core.wait(len(audio) / sample_rate)

trigger_patch.fillColor = (0, 0, RESET_VALUE)
trigger_patch.draw()
win.flip()

# --- Wait for keypress to exit ---
event.waitKeys()

dp.DPxDisableDoutPixelMode()
dp.DPxWriteRegCache()
dp.DPxClose()
win.close()
core.quit()
