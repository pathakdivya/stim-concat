"""End-to-end tests that really encode video.

These are the tests that protect the guarantee the whole tool rests on: that
the exported timeline describes the rendered file exactly. They are skipped
automatically if no FFmpeg binary can be found.
"""

from __future__ import annotations

import csv
import json
import subprocess

import pytest

from stim_concat import BuildConfig, build_all, scan_folder
from stim_concat.assignment.base import Assignment
from stim_concat.core.ffmpeg import FFmpegError, ffmpeg_path, ffprobe_path, probe
from stim_concat.core.renderer import VideoRenderer
from stim_concat.core.timeline import build_timeline

try:
    FFMPEG = ffmpeg_path()
except FFmpegError:  # pragma: no cover - depends on environment
    FFMPEG = None

pytestmark = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is not available")

FPS = 25
WIDTH, HEIGHT = 320, 240


def _run(args) -> None:
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture(scope="module")
def stimuli_dir(tmp_path_factory):
    """Three short real media files: video+audio, silent video, still image."""
    folder = tmp_path_factory.mktemp("stimuli")
    _run([
        "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=1.6",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1.6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "1.6",
        str(folder / "clip_001.mp4"),
    ])
    _run([
        "-f", "lavfi", "-i", "testsrc=size=200x200:rate=30:duration=1.2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "1.2",
        str(folder / "clip_002.mp4"),
    ])
    _run([
        "-f", "lavfi", "-i", "color=c=orange:s=100x80:d=1", "-frames:v", "1",
        str(folder / "clip_003.png"),
    ])
    return folder


@pytest.fixture
def config():
    config = BuildConfig()
    config.video.width, config.video.height, config.video.fps = WIDTH, HEIGHT, FPS
    config.video.preset = "ultrafast"
    config.instructions.opening_duration = 1.0
    config.instructions.closing_duration = 1.0
    config.instructions.default_duration = 0.6
    config.instructions.font_size = 20
    config.fixation.duration = 0.4
    config.layout.image_duration = 0.8
    return config


def _video_frames(path) -> int:
    probe_exe = ffprobe_path()
    if not probe_exe:  # pragma: no cover
        pytest.skip("ffprobe is required for frame counting")
    out = subprocess.run(
        [probe_exe, "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return int(json.loads(out.stdout)["streams"][0]["nb_read_frames"])


class TestProbe:
    def test_reads_duration_and_audio(self, stimuli_dir):
        info = probe(stimuli_dir / "clip_001.mp4")
        assert info.duration == pytest.approx(1.6, abs=0.05)
        assert info.has_video and info.has_audio
        assert (info.width, info.height) == (160, 120)

    def test_detects_silent_video(self, stimuli_dir):
        assert probe(stimuli_dir / "clip_002.mp4").has_audio is False

    def test_works_without_ffprobe(self, stimuli_dir, monkeypatch):
        """imageio-ffmpeg ships no ffprobe, so the banner fallback must work."""
        import stim_concat.core.ffmpeg as ffmpeg_module

        ffmpeg_module.clear_probe_cache()
        monkeypatch.setattr(ffmpeg_module, "ffprobe_path", lambda: None)
        info = ffmpeg_module.probe(stimuli_dir / "clip_001.mp4", use_cache=False)
        assert info.duration == pytest.approx(1.6, abs=0.05)
        assert (info.width, info.height) == (160, 120)
        assert info.has_audio


class TestRender:
    def test_timeline_matches_rendered_frames_exactly(self, stimuli_dir, tmp_path, config):
        """The guarantee: the timeline is the file, not an estimate of it."""
        stimuli = scan_folder(stimuli_dir)
        timeline = build_timeline("P001", stimuli.ids, stimuli, config)

        output = tmp_path / "P001.mp4"
        VideoRenderer(config).render(timeline, output)

        assert output.exists()
        assert _video_frames(output) == round(timeline.duration * FPS)
        assert probe(output).duration == pytest.approx(timeline.duration, abs=0.02)

    def test_output_uses_the_configured_geometry(self, stimuli_dir, tmp_path, config):
        stimuli = scan_folder(stimuli_dir)
        timeline = build_timeline("P001", stimuli.ids[:1], stimuli, config)
        output = tmp_path / "geom.mp4"
        VideoRenderer(config).render(timeline, output)
        info = probe(output)
        assert (info.width, info.height) == (WIDTH, HEIGHT)
        assert info.has_audio, "a silent build should still carry an audio track"

    def test_every_segment_boundary_is_frame_aligned(self, stimuli_dir, tmp_path, config):
        stimuli = scan_folder(stimuli_dir)
        timeline = build_timeline("P001", stimuli.ids, stimuli, config)
        for event in timeline:
            frames = event.start * FPS
            assert frames == pytest.approx(round(frames), abs=1e-6)

    def test_fixation_cross_is_drawn_where_configured(self, stimuli_dir, tmp_path, config):
        """Extract the middle frame of a fixation event and locate the cross."""
        numpy = pytest.importorskip("numpy")
        import io

        from PIL import Image

        config.fixation.size = 40
        config.fixation.thickness = 4
        stimuli = scan_folder(stimuli_dir)
        timeline = build_timeline("P001", stimuli.ids[:1], stimuli, config)
        output = tmp_path / "fix.mp4"
        VideoRenderer(config).render(timeline, output)

        fixation = next(e for e in timeline if e.event_type == "fixation")
        middle = (fixation.start + fixation.end) / 2
        frame = subprocess.run(
            [FFMPEG, "-v", "error", "-ss", str(middle), "-i", str(output),
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True, check=True,
        ).stdout
        pixels = numpy.array(Image.open(io.BytesIO(frame)).convert("L"))
        ys, xs = numpy.where(pixels > 200)
        assert len(xs), "the fixation cross should be visible"
        assert xs.mean() == pytest.approx(WIDTH / 2, abs=3)
        assert ys.mean() == pytest.approx(HEIGHT / 2, abs=3)
        assert xs.max() - xs.min() == pytest.approx(config.fixation.size, abs=3)

    def test_source_audio_is_preserved(self, stimuli_dir, tmp_path, config):
        stimuli = scan_folder(stimuli_dir)
        timeline = build_timeline("P001", ["clip_001"], stimuli, config)
        output = tmp_path / "audio.mp4"
        VideoRenderer(config).render(timeline, output)

        stimulus = next(e for e in timeline if e.event_type == "stimulus")
        result = subprocess.run(
            [FFMPEG, "-ss", str(stimulus.start + 0.2), "-t", "0.8", "-i", str(output),
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True,
        ).stderr
        mean = next(line for line in result.splitlines() if "mean_volume" in line)
        level = float(mean.split("mean_volume:")[1].split("dB")[0])
        assert level > -60, "the original tone should still be audible"

    def test_generated_screens_are_silent(self, stimuli_dir, tmp_path, config):
        stimuli = scan_folder(stimuli_dir)
        timeline = build_timeline("P001", ["clip_003"], stimuli, config)
        output = tmp_path / "silent.mp4"
        VideoRenderer(config).render(timeline, output)
        result = subprocess.run(
            [FFMPEG, "-ss", "0.2", "-t", "0.5", "-i", str(output),
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True,
        ).stderr
        mean = next(line for line in result.splitlines() if "mean_volume" in line)
        level = float(mean.split("mean_volume:")[1].split("dB")[0])
        assert level < -80, "instruction and fixation screens should be digitally silent"


class TestPipeline:
    def test_build_all_writes_every_output(self, stimuli_dir, tmp_path, config):
        stimuli = scan_folder(stimuli_dir)
        assignment = Assignment(
            participants=["P001", "P002"],
            rows=[["clip_001", "clip_003"], ["clip_002", "clip_001"]],
            algorithm="test",
            seed=1,
            stimulus_pool=stimuli.ids,
        )
        report = build_all(assignment, stimuli, config, tmp_path / "out")

        assert report.n_ok == 2 and report.n_failed == 0
        for participant in ("P001", "P002"):
            base = tmp_path / "out" / participant
            assert base.with_suffix(".mp4").exists()
            assert (tmp_path / "out" / f"{participant}_timeline.csv").exists()
            assert (tmp_path / "out" / f"{participant}_timeline.xlsx").exists()
            assert (tmp_path / "out" / f"{participant}_settings.json").exists()
        assert (tmp_path / "out" / "build_summary.csv").exists()
        assert (tmp_path / "out" / "build_summary.md").exists()

    def test_exported_timeline_matches_the_file_it_describes(self, stimuli_dir, tmp_path, config):
        stimuli = scan_folder(stimuli_dir)
        assignment = Assignment(
            participants=["P001"], rows=[["clip_001", "clip_002"]], stimulus_pool=stimuli.ids
        )
        build_all(assignment, stimuli, config, tmp_path / "out")

        rows = list(csv.DictReader((tmp_path / "out" / "P001_timeline.csv").open()))
        stated_end = float(rows[-1]["end_s"])
        assert _video_frames(tmp_path / "out" / "P001.mp4") == round(stated_end * FPS)

        # and the rows themselves are contiguous
        for previous, current in zip(rows, rows[1:]):
            assert float(previous["end_s"]) == pytest.approx(float(current["start_s"]), abs=0.001)

    def test_failures_are_reported_not_raised(self, stimuli_dir, tmp_path, config):
        stimuli = scan_folder(stimuli_dir)
        assignment = Assignment(
            participants=["P001", "P002"],
            rows=[["clip_001"], ["ghost"]],
            stimulus_pool=[*stimuli.ids, "ghost"],
        )
        report = build_all(assignment, stimuli, config, tmp_path / "out")
        assert report.n_ok == 1
        assert report.n_failed == 1
        assert "ghost" in report.results[1].message

    def test_settings_json_can_rebuild_the_same_config(self, stimuli_dir, tmp_path, config):
        stimuli = scan_folder(stimuli_dir)
        assignment = Assignment(participants=["P001"], rows=[["clip_003"]], stimulus_pool=stimuli.ids)
        build_all(assignment, stimuli, config, tmp_path / "out")

        restored = BuildConfig.from_json(tmp_path / "out" / "P001_settings.json")
        assert restored.video.width == config.video.width
        assert restored.video.fps == config.video.fps
        assert restored.timeline.trial_sequence == config.timeline.trial_sequence
