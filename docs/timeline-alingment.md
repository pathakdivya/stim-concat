# Aligning recordings with the timeline

The timeline file is the reason `stim-concat` exists. This page shows how to use
it to cut a continuous recording — eye-tracking samples, joystick or gamepad
ratings, skin conductance, respiration — into per-stimulus epochs.

## What the timeline gives you

`P001_timeline.csv` has one row per event, with times in seconds measured from
the first frame of `P001.mp4`:

| event_index | start_s | end_s | duration_s | event_type | trial | stimulus_id | description | source_file |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 0.000 | 8.000 | 8.000 | instruction | | | Opening instructions | |
| 1 | 8.000 | 9.000 | 1.000 | fixation | 1 | | Fixation cross | |
| 2 | 9.000 | 12.000 | 3.000 | instruction | 1 | 070 | Default instruction | |
| 3 | 12.000 | 27.372 | 15.372 | stimulus | 1 | 070 | Video | clip_070.mp4 |

These boundaries are exact, not approximate: durations are quantised to whole
frames before rendering, and each segment is pinned to a computed frame count.
`start_s * fps` is always a whole number, so you can convert to frame indices
without worrying about accumulated rounding.

## The one thing you must record

The timeline is relative to video onset, so your recording needs a **t = 0**
marker — the moment the first video frame appeared. Options, roughly in order of
reliability:

1. A hardware trigger or photodiode on the first frame.
2. A TTL/event marker written by your recording software when playback starts.
3. A software timestamp taken as close to playback start as you can manage
   (adequate for slow continuous measures, weak for anything needing
   millisecond accuracy).

Everything below assumes you have that onset timestamp.

## Cutting a recording into epochs

```python
import pandas as pd

timeline = pd.read_csv("output/P001_timeline.csv")
recording = pd.read_csv("recordings/P001_joystick.csv")   # columns: t, valence, arousal

# Put the recording on the same clock as the video.
VIDEO_ONSET = 1_718_000.000          # your recorded onset, same units as recording["t"]
recording["t_video"] = recording["t"] - VIDEO_ONSET

stimuli = timeline[timeline.event_type == "stimulus"]

epochs = []
for row in stimuli.itertuples():
    segment = recording[
        (recording.t_video >= row.start_s) & (recording.t_video < row.end_s)
    ].copy()
    segment["stimulus_id"] = row.stimulus_id
    segment["trial"] = row.trial
    segment["t_stimulus"] = segment.t_video - row.start_s   # time from stimulus onset
    epochs.append(segment)

epochs = pd.concat(epochs, ignore_index=True)
```

`t_stimulus` is what you usually want on the x-axis: time since that stimulus
began, comparable across participants even though each saw a different order.

A faster equivalent for large recordings, using an interval index:

```python
bins = pd.IntervalIndex.from_arrays(stimuli.start_s, stimuli.end_s, closed="left")
recording["trial"] = pd.cut(recording.t_video, bins).map(
    dict(zip(bins, stimuli.trial))
)
```

## Baselines from the fixation events

Fixation crosses make natural baseline windows, and they are in the timeline
too:

```python
fixations = timeline[timeline.event_type == "fixation"]

def baseline_for(trial):
    window = fixations[fixations.trial == trial]
    if window.empty:
        return None
    row = window.iloc[0]
    mask = (recording.t_video >= row.start_s) & (recording.t_video < row.end_s)
    return recording.loc[mask, "arousal"].mean()
```

## Sanity checks worth running once

```python
# 1. The recording covers the whole session.
assert recording.t_video.max() >= timeline.end_s.max(), "recording ends early"

# 2. Events are contiguous — a gap means the file was edited.
assert (timeline.start_s.iloc[1:].values == timeline.end_s.iloc[:-1].values).all()

# 3. The video really is as long as the timeline says.
#    ffprobe -v error -show_entries format=duration -of csv=p=0 output/P001.mp4
```

If check 3 disagrees by more than a frame, something re-encoded the file after
`stim-concat` produced it.

## Which stimuli did this participant see?

Both `P001_settings.json` and the assignment sheet record it, but the timeline
is self-contained:

```python
order = timeline.query("event_type == 'stimulus'")[["trial", "stimulus_id"]]
```

Because assignment is participant-specific, always take the order from that
participant's own timeline rather than assuming a fixed sequence.

## Eye-tracking in screen coordinates

If the stimulus was not drawn full-screen, gaze coordinates need shifting into
stimulus space. `*_settings.json` records the layout that was used:

```python
import json

settings = json.load(open("output/P001_settings.json"))
layout = settings["layout"]        # fit, position, offset_x, offset_y, scale
video = settings["video"]          # width, height
```

With `fit: "contain"` and `position: "center"`, a stimulus of native size
`(w, h)` is scaled by `min(W/w, H/h) * scale` and centred, so the letterbox
offset is `((W - w'), (H - h')) / 2` plus any configured nudge.
