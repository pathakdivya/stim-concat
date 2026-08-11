---
title: 'stim-concat: participant-specific concatenated stimulus and stimulus assignment for behavioural experiments'
tags:
  - Python
  - psychology
  - neuroscience
  - stimulus presentation
  - counterbalancing
authors:
  - name: "Divya Pathak"
    orcid: 0000-0001-6837-0700
    affiliation: 1
affiliations:
  - name: "Department of Cognitive Science, IIT Kanpur"
    index: 1
date: 2026
bibliography: paper.bib
---

# Summary

`stim-concat` converts a folder of stimulus files into one concatenated video
per participant, accompanied by an annotated timeline listing every event in
that video. Researchers specify how many participants they have, how many
stimuli each should see, and which experimental design should allocate them;
the software generates the assignment sheet, then renders each participant's
session — opening instructions, fixation crosses, per-trial instructions,
stimuli in the assigned order, and a closing screen — into a single MP4 file.

Because a session is one ordinary video, it can be presented by anything that
plays video. The timeline file, which reports the start and end time of every
event to the frame, is then used to align concurrently recorded eye-tracking,
continuous rating, or physiological data with the stimuli that produced them.

# Statement of need

Behavioural experiments that present video or audio stimuli typically rely on
presentation frameworks such as PsychoPy [@Peirce2019], Psychtoolbox
[@Brainard1997], OpenSesame [@Mathot2012], or E-Prime. These are powerful and
appropriate when an experiment needs trial-by-trial response collection or
adaptive control. They are a poor fit for a common and simpler case: a
participant watches a fixed sequence of clips while some *other* system records
continuously.

That case arises whenever the recording apparatus is not the presentation
apparatus — a standalone eye-tracker, a gamepad or joystick continuous-rating
interface, an EEG or physiological amplifier, an fMRI console, or a custom
application. Researchers in this situation face three recurring difficulties.
First, integrating a presentation framework with the recording system requires
programming effort disproportionate to the design, and often introduces a second
clock. Second, participant-specific stimulus assignment is frequently done by
hand in spreadsheets, an error-prone and poorly documented process. Third,
concatenating stimuli with generic video tools produces a file whose event
boundaries are approximately, but not exactly, where the researcher believes
them to be — and that error is inherited by every downstream alignment.

`stim-concat` addresses these by moving presentation into an offline rendering
step whose output is exact and self-documenting. Only two artefacts are needed
to reconstruct a study: an assignment sheet with its provenance metadata, and a
settings file describing the render.

# Functionality

The software has two stages, exposed identically through a five-page wizard, a
command line interface, and a Python API.

**Assignment.** A stimulus folder is scanned for video, image, audio, and text
files; stimulus identifiers are extracted from filenames using a configurable
regular expression. Seven designs are provided: simple random sampling, sampling
without replacement, balanced random assignment, block randomisation, Latin
square with an optional Williams construction balancing first-order carry-over
effects, balanced incomplete block designs (BIBD), and pseudorandom assignment
under sequencing constraints.

Each algorithm is a standalone, documented Python script displayed in an editor
inside the application: the code shown is the code that runs. Researchers can
inspect it, modify it, run the modified version, and save it as a new algorithm.
The exact source that produced a sheet is stored alongside it, together with the
random seed, parameters, and a fingerprint of the stimulus pool.

Where a design is mathematically unavailable the software says so rather than
silently approximating. An exact BIBD requires $r = bk/v$ and
$\lambda = r(k-1)/(v-1)$ to be integers; the search recovers known designs such
as the Fano plane and the projective plane of order 3, and where no exact design
exists it reports the residual imbalance while still guaranteeing balanced
replication.

**Building.** For each participant the software constructs an event timeline and
renders it. The order of fixation, instruction, stimulus, and blank elements
within a trial is configurable, as are fixation geometry and colour, instruction
text and typography (including per-stimulus overrides), stimulus position and
scaling, background colours, resolution, frame rate, codec, quality, and audio
handling. Source audio is preserved by default.

**Timing.** The timeline is exact rather than estimated. Durations are quantised
to whole frames before rendering; each segment is pinned to a computed frame
count instead of a nominal duration, which eliminates per-segment rounding drift;
and intermediate segments carry uncompressed audio so that both streams are cut
at exact boundaries, with the audio encoded once when segments are joined by
stream copy. The test suite asserts that the rendered frame count equals the
frame count implied by the exported timeline.

Instruction and fixation screens are drawn with Pillow [@Clark2015] rather than
FFmpeg's `drawtext` filter, because widely distributed static FFmpeg builds —
including those bundled for self-contained installation — are compiled without
libfreetype. This also allows text to be wrapped by measured pixel width.

Per participant the software writes the video, the timeline as CSV and as a
colour-coded spreadsheet, and a JSON settings file recording the full
configuration and the FFmpeg version used; a build summary covers the whole run.

# Comparison with existing tools

General-purpose tools such as FFmpeg or MoviePy can concatenate media, but
provide neither experimental design support nor event annotation, and require
the researcher to reason about frame-accurate concatenation. Presentation
frameworks provide design support and precise timing but must drive the
experiment, which is the assumption `stim-concat` is built to remove.
`stim-concat` occupies the space between: design-aware, annotation-producing,
and agnostic about how the resulting video is played and recorded.

# Acknowledgements

We thank the FFmpeg and Pillow projects, on which this software depends.

# References
