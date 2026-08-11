"""Tests for the parts of stim-concat that do not need to encode video."""

from __future__ import annotations

import json
from itertools import combinations

import pytest

from stim_concat import BuildConfig, scan_folder
from stim_concat.assignment.base import Assignment, AssignmentError, stimulus_fingerprint
from stim_concat.assignment.registry import (
    compile_algorithm,
    discover,
    get,
    run_algorithm,
    run_source,
)
from stim_concat.core.config import FixationConfig, InstructionConfig, VideoConfig
from stim_concat.core.scanner import (
    NUMERIC_ID_PATTERN,
    extract_id,
    kind_for,
    register_format,
    supported_extensions,
)
from stim_concat.core.timeline import build_timeline


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def stimulus_folder(tmp_path):
    """A folder of dummy files, enough for scanning and assignment tests."""
    folder = tmp_path / "stimuli"
    folder.mkdir()
    for name in (
        "happy_001.mp4",
        "happy_002.mov",
        "sad_003.avi",
        "sad_004.mkv",
        "neutral_005.png",
        "neutral_006.jpg",
        "tone_007.mp3",
        "notes_008.txt",
        "readme.pdf",  # unsupported: must be ignored
        ".hidden.mp4",  # hidden: must be ignored
    ):
        (folder / name).write_bytes(b"x")
    return folder


@pytest.fixture
def ids():
    return [f"{i:03d}" for i in range(1, 13)]


# --------------------------------------------------------------------------
# scanner
# --------------------------------------------------------------------------
class TestScanner:
    def test_finds_supported_files_only(self, stimulus_folder):
        stimuli = scan_folder(stimulus_folder)
        assert len(stimuli) == 8
        assert "readme" not in stimuli.ids
        assert not any(name.startswith(".") for name in (s.name for s in stimuli))

    def test_media_kinds(self, stimulus_folder):
        counts = scan_folder(stimulus_folder).counts_by_kind()
        assert counts == {"video": 4, "image": 2, "audio": 1, "text": 1}

    def test_numeric_id_pattern(self, stimulus_folder):
        stimuli = scan_folder(stimulus_folder, id_pattern=NUMERIC_ID_PATTERN)
        # Files are listed in natural filename order, so the IDs follow the
        # filenames (happy_001, happy_002, neutral_005, ...) rather than sorting
        # numerically themselves.
        assert stimuli.ids == ["001", "002", "005", "006", "008", "003", "004", "007"]
        assert sorted(stimuli.ids) == [f"{i:03d}" for i in range(1, 9)]

    def test_natural_sort_order(self, tmp_path):
        folder = tmp_path / "s"
        folder.mkdir()
        for name in ("clip_2.mp4", "clip_10.mp4", "clip_1.mp4"):
            (folder / name).write_bytes(b"x")
        assert scan_folder(folder).ids == ["clip_1", "clip_2", "clip_10"]

    def test_lookup_tolerates_zero_padding(self, stimulus_folder):
        stimuli = scan_folder(stimulus_folder, id_pattern=NUMERIC_ID_PATTERN)
        assert stimuli.get("7") is stimuli.get("007")
        assert stimuli.get("999") is None

    def test_require_raises_for_unknown_id(self, stimulus_folder):
        with pytest.raises(KeyError):
            scan_folder(stimulus_folder).require("nope")

    def test_duplicate_ids_are_reported(self, tmp_path):
        folder = tmp_path / "s"
        folder.mkdir()
        (folder / "clip_001.mp4").write_bytes(b"x")
        (folder / "clip_001.mov").write_bytes(b"x")
        stimuli = scan_folder(folder, id_pattern=NUMERIC_ID_PATTERN)
        assert "001" in stimuli.duplicates

    def test_missing_reports_unresolvable_ids(self, stimulus_folder):
        stimuli = scan_folder(stimulus_folder)
        assert stimuli.missing(["happy_001", "ghost"]) == ["ghost"]

    def test_register_new_format(self):
        register_format(".xyz", "video")
        assert kind_for("a.xyz") == "video"
        assert ".xyz" in supported_extensions()

    def test_extract_id_variants(self):
        assert extract_id("clip_070_sad.mp4") == "clip_070_sad"
        assert extract_id("clip_070_sad.mp4", NUMERIC_ID_PATTERN) == "070"
        assert extract_id("clip_070.mp4", r"(?P<id>[^_]+)$") == "070"

    def test_recursive_scan(self, tmp_path):
        folder = tmp_path / "s"
        (folder / "sub").mkdir(parents=True)
        (folder / "a.mp4").write_bytes(b"x")
        (folder / "sub" / "b.mp4").write_bytes(b"x")
        assert len(scan_folder(folder)) == 1
        assert len(scan_folder(folder, recursive=True)) == 2

    def test_missing_folder_raises(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            scan_folder(tmp_path / "nope")


# --------------------------------------------------------------------------
# algorithm registry
# --------------------------------------------------------------------------
class TestRegistry:
    def test_seven_builtin_algorithms(self):
        keys = {spec.key for spec in discover()}
        assert {
            "simple_random",
            "random_without_replacement",
            "balanced_random",
            "block_randomisation",
            "latin_square",
            "bibd",
            "constrained_pseudorandom",
        } <= keys

    def test_every_builtin_declares_metadata(self):
        for spec in discover():
            assert spec.name and spec.description
            assert isinstance(spec.params, list)

    def test_get_unknown_key(self):
        with pytest.raises(KeyError):
            get("does_not_exist")

    def test_script_without_assign_is_rejected(self):
        with pytest.raises(AssignmentError, match="assign"):
            compile_algorithm("NAME = 'x'")

    def test_syntax_error_is_reported_with_line(self):
        with pytest.raises(AssignmentError, match="Syntax error"):
            compile_algorithm("def assign(:\n    pass")

    def test_edited_source_overrides_the_file(self, ids):
        source = (
            "NAME='fixed'\n"
            "def assign(stimuli, n_participants, n_per_participant, rng, params):\n"
            "    return [stimuli[:n_per_participant] for _ in range(n_participants)]\n"
        )
        result = run_algorithm("simple_random", ids, 3, 2, source=source)
        assert all(row == ids[:2] for row in result.rows)
        assert result.script == source  # stored for reproducibility

    def test_wrong_row_count_is_caught(self, ids):
        source = (
            "def assign(stimuli, n_participants, n_per_participant, rng, params):\n"
            "    return [stimuli[:n_per_participant]]\n"
        )
        with pytest.raises(AssignmentError, match="returned 1 rows"):
            run_source(source, ids, 4, 2)

    def test_wrong_trial_count_is_caught(self, ids):
        source = (
            "def assign(stimuli, n_participants, n_per_participant, rng, params):\n"
            "    return [stimuli[:1] for _ in range(n_participants)]\n"
        )
        with pytest.raises(AssignmentError, match="wrong number of trials"):
            run_source(source, ids, 3, 4)

    def test_unknown_stimulus_is_caught(self, ids):
        source = (
            "def assign(stimuli, n_participants, n_per_participant, rng, params):\n"
            "    return [['ghost'] * n_per_participant for _ in range(n_participants)]\n"
        )
        with pytest.raises(AssignmentError, match="not in the folder"):
            run_source(source, ids, 2, 2)

    def test_exception_inside_script_is_wrapped(self, ids):
        source = (
            "def assign(stimuli, n_participants, n_per_participant, rng, params):\n"
            "    raise RuntimeError('boom')\n"
        )
        with pytest.raises(AssignmentError, match="boom"):
            run_source(source, ids, 2, 2)

    def test_empty_pool_rejected(self):
        with pytest.raises(AssignmentError):
            run_algorithm("simple_random", [], 2, 2)


# --------------------------------------------------------------------------
# algorithms
# --------------------------------------------------------------------------
ALL_ALGORITHMS = [
    "simple_random",
    "random_without_replacement",
    "balanced_random",
    "block_randomisation",
    "latin_square",
    "bibd",
    "constrained_pseudorandom",
]


class TestAlgorithms:
    @pytest.mark.parametrize("key", ALL_ALGORITHMS)
    def test_shape_is_correct(self, key, ids):
        result = run_algorithm(key, ids, 6, 4, seed=1)
        assert result.n_participants == 6
        assert all(len(row) == 4 for row in result.rows)
        assert {s for row in result.rows for s in row} <= set(ids)

    @pytest.mark.parametrize("key", ALL_ALGORITHMS)
    def test_seed_is_reproducible(self, key, ids):
        first = run_algorithm(key, ids, 6, 4, seed=99)
        second = run_algorithm(key, ids, 6, 4, seed=99)
        assert first.rows == second.rows

    @pytest.mark.parametrize("key", ALL_ALGORITHMS)
    def test_different_seeds_differ(self, key, ids):
        first = run_algorithm(key, ids, 8, 4, seed=1)
        second = run_algorithm(key, ids, 8, 4, seed=2)
        assert first.rows != second.rows

    @pytest.mark.parametrize(
        "key", ["random_without_replacement", "balanced_random", "latin_square", "bibd"]
    )
    def test_no_repeats_within_participant(self, key, ids):
        for row in run_algorithm(key, ids, 8, 5, seed=3).rows:
            assert len(set(row)) == len(row)

    def test_balanced_random_equalises_exposure(self, ids):
        # 12 stimuli, 6 participants x 4 trials = 24 slots = exactly 2 each
        counts = run_algorithm("balanced_random", ids, 6, 4, seed=5).usage_counts()
        assert set(counts.values()) == {2}

    def test_without_replacement_needs_a_big_enough_pool(self, ids):
        with pytest.raises(AssignmentError, match="Cannot draw"):
            run_algorithm("random_without_replacement", ids, 3, len(ids) + 1)

    def test_latin_square_covers_every_position(self):
        pool = ["a", "b", "c", "d"]
        rows = run_algorithm("latin_square", pool, 4, 4, seed=11).rows
        for position in range(4):
            assert sorted(row[position] for row in rows) == sorted(pool)

    def test_williams_square_balances_carry_over(self):
        """Each stimulus should follow every other one equally often."""
        pool = ["a", "b", "c", "d"]
        rows = run_algorithm("latin_square", pool, 4, 4, seed=2).rows
        pairs: dict[tuple[str, str], int] = {}
        for row in rows:
            for first, second in zip(row, row[1:]):
                pairs[(first, second)] = pairs.get((first, second), 0) + 1
        assert set(pairs.values()) == {1}

    @pytest.mark.parametrize("v,b,k,lam", [(7, 7, 3, 1), (13, 13, 4, 1), (9, 12, 3, 1)])
    def test_bibd_finds_exact_designs(self, v, b, k, lam):
        pool = [f"{i:03d}" for i in range(v)]
        result = run_algorithm("bibd", pool, b, k, seed=7)
        pairs: dict[tuple[str, str], int] = {}
        for row in result.rows:
            for x, y in combinations(sorted(row), 2):
                pairs[(x, y)] = pairs.get((x, y), 0) + 1
        assert len(pairs) == v * (v - 1) // 2, "every pair must co-occur"
        assert set(pairs.values()) == {lam}
        assert set(result.usage_counts().values()) == {b * k // v}

    def test_bibd_keeps_replication_balanced_when_no_exact_design_exists(self):
        pool = [f"{i:03d}" for i in range(8)]
        result = run_algorithm("bibd", pool, 6, 4, seed=42)
        assert set(result.usage_counts().values()) == {3}
        assert "No exact BIBD exists" in result.notes

    def test_bibd_can_demand_an_exact_design(self):
        pool = [f"{i:03d}" for i in range(8)]
        with pytest.raises(AssignmentError, match="No exact BIBD"):
            run_algorithm("bibd", pool, 6, 4, seed=1, params={"require_exact": True})

    def test_block_randomisation_uses_filename_groups(self):
        pool = [f"{mood}_{i:03d}" for mood in ("happy", "sad") for i in range(1, 5)]
        rows = run_algorithm(
            "block_randomisation",
            pool,
            10,
            2,
            seed=4,
            params={"group_pattern": r"^(?P<group>[a-z]+)"},
        ).rows
        for row in rows:
            moods = sorted(s.split("_")[0] for s in row)
            assert moods == ["happy", "sad"], "one stimulus from each condition"

    def test_constrained_limits_category_runs(self):
        pool = [f"{mood}_{i:03d}" for mood in ("happy", "sad", "neutral") for i in range(1, 5)]
        result = run_algorithm(
            "constrained_pseudorandom",
            pool,
            8,
            6,
            seed=6,
            params={"category_pattern": r"^(?P<group>[a-z]+)", "max_same_category_run": 2},
        )
        assert "All constraints satisfied" in result.notes
        for row in result.rows:
            run, previous = 1, row[0].split("_")[0]
            for stimulus in row[1:]:
                current = stimulus.split("_")[0]
                run = run + 1 if current == previous else 1
                assert run <= 2
                previous = current

    def test_simple_random_may_repeat(self, ids):
        rows = run_algorithm("simple_random", ids[:3], 20, 5, seed=8).rows
        assert any(len(set(row)) < len(row) for row in rows)


# --------------------------------------------------------------------------
# assignment I/O
# --------------------------------------------------------------------------
class TestAssignmentIO:
    def test_csv_round_trip(self, tmp_path, ids):
        original = run_algorithm("balanced_random", ids, 5, 3, seed=12)
        path = tmp_path / "assignments.csv"
        original.to_csv(path)
        restored = Assignment.from_csv(path)
        assert restored.rows == original.rows
        assert restored.participants == original.participants

    def test_metadata_sidecar_records_provenance(self, tmp_path, ids):
        original = run_algorithm("bibd", ids, 4, 3, seed=12)
        path = tmp_path / "a.csv"
        original.to_csv(path)
        meta = json.loads(Assignment.metadata_path(path).read_text())
        assert meta["seed"] == 12
        assert meta["stimulus_fingerprint"] == stimulus_fingerprint(ids)
        assert "def assign" in meta["script"], "the exact script must be stored"

    def test_import_without_a_participant_column(self, tmp_path):
        path = tmp_path / "plain.csv"
        path.write_text("trial_1,trial_2\n001,002\n003,004\n")
        assignment = Assignment.from_csv(path)
        assert assignment.participants == ["P001", "P002"]
        assert assignment.rows == [["001", "002"], ["003", "004"]]

    def test_empty_csv_raises(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("")
        with pytest.raises(AssignmentError):
            Assignment.from_csv(path)

    def test_validate_flags_unknown_stimuli(self, ids):
        assignment = Assignment(participants=["P001"], rows=[["ghost"]])
        problems = assignment.validate(ids)
        assert any("not in the folder" in p for p in problems)

    def test_validate_flags_ragged_rows(self):
        assignment = Assignment(participants=["P001", "P002"], rows=[["a"], ["a", "b"]])
        assert any("different trial counts" in p for p in assignment.validate())

    def test_balance_report(self, ids):
        report = run_algorithm("balanced_random", ids, 6, 4, seed=5).balance_report()
        assert report["min_uses"] == report["max_uses"] == 2
        assert report["coverage"] == 1.0


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------
class TestConfig:
    def test_json_round_trip(self, tmp_path):
        config = BuildConfig()
        config.video.width, config.video.height = 1920, 1080
        config.fixation.color = "#FF0000"
        config.instructions.per_stimulus["001"] = {"text": "hi", "duration": 2.0}
        config.timeline.trial_sequence = ["instruction", "stimulus", "blank"]

        path = tmp_path / "settings.json"
        config.to_json(path)
        restored = BuildConfig.from_json(path)

        assert restored.video.width == 1920
        assert restored.fixation.color == "#FF0000"
        assert restored.instructions.per_stimulus["001"]["text"] == "hi"
        assert restored.timeline.trial_sequence == ["instruction", "stimulus", "blank"]

    def test_quantise_snaps_to_frames(self):
        video = VideoConfig(fps=30)
        assert video.quantise(1.0) == 1.0
        assert video.quantise(1.004) == pytest.approx(1.0)
        assert video.quantise(1.02) == pytest.approx(31 / 30)

    def test_odd_dimensions_rejected(self):
        config = BuildConfig()
        config.video.width = 1281
        assert any("even" in p for p in config.validate())

    def test_sequence_must_contain_stimulus(self):
        config = BuildConfig()
        config.timeline.trial_sequence = ["fixation"]
        assert any("must contain 'stimulus'" in p for p in config.validate())

    def test_unknown_sequence_element_rejected(self):
        config = BuildConfig()
        config.timeline.trial_sequence = ["stimulus", "banana"]
        assert any("banana" in p for p in config.validate())

    def test_per_stimulus_override_lookup(self):
        instructions = InstructionConfig(default_text="default", default_duration=3.0)
        instructions.per_stimulus["007"] = {"text": "special", "duration": 5.0}
        assert instructions.for_stimulus("007") == ("special", 5.0)
        assert instructions.for_stimulus("008") == ("default", 3.0)
        assert instructions.has_override("007")


# --------------------------------------------------------------------------
# timeline
# --------------------------------------------------------------------------
class TestTimeline:
    def _config(self):
        config = BuildConfig()
        config.video = VideoConfig(width=320, height=240, fps=25)
        config.fixation = FixationConfig(enabled=True, duration=1.0)
        config.instructions.opening_duration = 4.0
        config.instructions.closing_duration = 2.0
        config.instructions.default_duration = 3.0
        config.layout.image_duration = 2.0
        return config

    def _images(self, tmp_path, n=3):
        """Images only, so the timeline needs no media probing."""
        folder = tmp_path / "img"
        folder.mkdir()
        for i in range(1, n + 1):
            (folder / f"stim_{i:03d}.png").write_bytes(b"x")
        return scan_folder(folder)

    def test_events_are_contiguous(self, tmp_path):
        stimuli = self._images(tmp_path)
        timeline = build_timeline("P001", stimuli.ids, stimuli, self._config())
        for previous, current in zip(timeline, list(timeline)[1:]):
            assert previous.end == current.start, "no gaps or overlaps allowed"
        assert timeline[0].start == 0.0

    def test_structure_matches_the_configured_order(self, tmp_path):
        stimuli = self._images(tmp_path, 2)
        timeline = build_timeline("P001", stimuli.ids, stimuli, self._config())
        assert [e.event_type for e in timeline] == [
            "instruction",  # opening
            "fixation", "instruction", "stimulus",  # trial 1
            "fixation", "instruction", "stimulus",  # trial 2
            "fixation",  # trailing
            "instruction",  # closing
        ]

    def test_total_duration_is_the_sum_of_events(self, tmp_path):
        stimuli = self._images(tmp_path, 2)
        timeline = build_timeline("P001", stimuli.ids, stimuli, self._config())
        # 4 opening + 2 x (1 fixation + 3 instruction + 2 image) + 1 fixation + 2 closing
        assert timeline.duration == pytest.approx(4 + 2 * 6 + 1 + 2)

    def test_every_duration_is_a_whole_number_of_frames(self, tmp_path):
        stimuli = self._images(tmp_path)
        config = self._config()
        config.instructions.opening_duration = 4.017  # deliberately off-grid
        timeline = build_timeline("P001", stimuli.ids, stimuli, config)
        for event in timeline:
            frames = event.duration * config.video.fps
            assert frames == pytest.approx(round(frames), abs=1e-6)

    def test_per_stimulus_override_is_used(self, tmp_path):
        stimuli = self._images(tmp_path, 2)
        config = self._config()
        config.instructions.per_stimulus[stimuli.ids[0]] = {"text": "special", "duration": 7.0}
        timeline = build_timeline("P001", stimuli.ids, stimuli, config)
        overridden = [e for e in timeline if e.description == "Per-stimulus instruction"]
        assert len(overridden) == 1
        assert overridden[0].duration == 7.0
        assert overridden[0].spec["text"] == "special"

    def test_disabled_elements_are_omitted(self, tmp_path):
        stimuli = self._images(tmp_path, 2)
        config = self._config()
        config.fixation.enabled = False
        config.instructions.opening_enabled = False
        config.instructions.closing_enabled = False
        config.instructions.interleaved_enabled = False
        timeline = build_timeline("P001", stimuli.ids, stimuli, config)
        assert [e.event_type for e in timeline] == ["stimulus", "stimulus"]

    def test_custom_sequence_with_blank(self, tmp_path):
        stimuli = self._images(tmp_path, 1)
        config = self._config()
        config.timeline.trial_sequence = ["stimulus", "blank"]
        config.timeline.trailing_sequence = []
        config.instructions.opening_enabled = False
        config.instructions.closing_enabled = False
        timeline = build_timeline("P001", stimuli.ids, stimuli, config)
        assert [e.event_type for e in timeline] == ["stimulus", "blank"]

    def test_trial_numbers_are_recorded(self, tmp_path):
        stimuli = self._images(tmp_path, 3)
        timeline = build_timeline("P001", stimuli.ids, stimuli, self._config())
        assert [e.trial for e in timeline.stimulus_events] == [1, 2, 3]

    def test_unknown_stimulus_raises(self, tmp_path):
        stimuli = self._images(tmp_path, 1)
        with pytest.raises(KeyError):
            build_timeline("P001", ["ghost"], stimuli, self._config())

    def test_invalid_config_raises(self, tmp_path):
        stimuli = self._images(tmp_path, 1)
        config = self._config()
        config.timeline.trial_sequence = ["fixation"]
        with pytest.raises(ValueError, match="Invalid configuration"):
            build_timeline("P001", stimuli.ids, stimuli, config)

    def test_rows_have_the_documented_columns(self, tmp_path):
        from stim_concat.core.timeline import TIMELINE_COLUMNS

        stimuli = self._images(tmp_path, 1)
        timeline = build_timeline("P001", stimuli.ids, stimuli, self._config())
        assert set(timeline.rows()[0]) == set(TIMELINE_COLUMNS)


# --------------------------------------------------------------------------
# exporters
# --------------------------------------------------------------------------
class TestExporters:
    def _timeline(self, tmp_path):
        folder = tmp_path / "img"
        folder.mkdir()
        (folder / "stim_001.png").write_bytes(b"x")
        stimuli = scan_folder(folder)
        return build_timeline("P001", stimuli.ids, stimuli, BuildConfig())

    def test_timeline_csv(self, tmp_path):
        import csv

        from stim_concat.core.exporters import write_timeline_csv

        timeline = self._timeline(tmp_path)
        path = write_timeline_csv(timeline, tmp_path / "t.csv")
        rows = list(csv.DictReader(path.open()))
        assert len(rows) == len(timeline)
        assert float(rows[-1]["end_s"]) == pytest.approx(timeline.duration, abs=0.001)

    def test_timeline_xlsx(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        from stim_concat.core.exporters import write_timeline_xlsx

        timeline = self._timeline(tmp_path)
        path = write_timeline_xlsx(timeline, tmp_path / "t.xlsx")
        sheet = openpyxl.load_workbook(path)["timeline"]
        assert sheet.cell(row=1, column=1).value == "event_index"
        assert sheet.max_row >= len(timeline) + 1

    def test_settings_json_records_provenance(self, tmp_path):
        from stim_concat.core.exporters import write_settings_json

        path = write_settings_json(
            BuildConfig(),
            tmp_path / "s.json",
            participant="P001",
            stimulus_ids=["001", "002"],
            ffmpeg_version="ffmpeg 7.0",
        )
        data = json.loads(path.read_text())
        assert data["_meta"]["participant"] == "P001"
        assert data["_meta"]["stimulus_ids"] == ["001", "002"]
        assert data["video"]["fps"] == 30.0
