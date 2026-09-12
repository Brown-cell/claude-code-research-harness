"""Tests for the two handoff hooks.

The decision the Stop hook makes -- soft line, hard line, or stay quiet -- is
pulled out into small pure functions precisely so it can be tested without a
harness, a transcript or a clock. The parts that touch the filesystem
(transcript parsing, the cooldown marker, the track list) get their own tests
with real temporary files.
"""
import importlib.util
import json
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name):
    path = ROOT / "hooks" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


stop = _load("handoff_stop.py")
start = _load("handoff_sessionstart.py")


# --- thresholds ------------------------------------------------------------

def test_default_lines_are_90k_and_150k():
    assert stop.lines_for("claude-sonnet", env={}) == (90_000, 150_000)
    assert stop.lines_for("", env={}) == (90_000, 150_000)
    assert stop.lines_for(None, env={}) == (90_000, 150_000)


def test_every_public_model_has_an_entry():
    for model in ("opus", "sonnet", "haiku"):
        assert model in stop.MODEL_LINES


def test_model_table_is_matched_as_a_substring():
    """Model ids carry suffixes, so the table cannot be keyed on equality."""
    assert stop.lines_for("claude-opus-4-5-20260101", env={}) == \
        stop.MODEL_LINES["opus"]


def test_environment_overrides_win():
    assert stop.lines_for("sonnet", env={"HANDOFF_SOFT": "10000"}) == \
        (10_000, 150_000)
    assert stop.lines_for("sonnet", env={"HANDOFF_HARD": "20000"}) == \
        (90_000, 20_000)
    assert stop.lines_for("sonnet", env={"HANDOFF_SOFT": "5000",
                                         "HANDOFF_HARD": "6000"}) == (5_000, 6_000)


def test_unparseable_override_is_ignored_not_fatal():
    assert stop.lines_for("sonnet", env={"HANDOFF_SOFT": "later"}) == \
        (90_000, 150_000)


def test_tier_boundaries():
    assert stop.tier(89_999, 90_000, 150_000) is None
    assert stop.tier(90_000, 90_000, 150_000) == "soft"     # inclusive
    assert stop.tier(149_999, 90_000, 150_000) == "soft"
    assert stop.tier(150_000, 90_000, 150_000) == "hard"    # inclusive
    assert stop.tier(600_000, 90_000, 150_000) == "hard"


def test_cooldown_widens_once_the_nag_is_being_ignored():
    assert stop.cooldown_minutes(0) == 10
    assert stop.cooldown_minutes(2) == 10
    assert stop.cooldown_minutes(3) == 30
    assert stop.cooldown_minutes(9) == 30


def test_per_turn_cost_is_a_tenth_of_the_window():
    assert stop.per_turn_cost(300_000) == 30
    assert stop.per_turn_cost(90_000) == 9


# --- transcript reading ----------------------------------------------------

def _turn(tokens, model="claude-sonnet-4", sidechain=False):
    return json.dumps({
        "type": "assistant",
        "isSidechain": sidechain,
        "message": {"role": "assistant", "model": model,
                    "usage": {"input_tokens": tokens,
                              "cache_creation_input_tokens": 0,
                              "cache_read_input_tokens": 0}},
    })


def test_latest_usage_sums_the_three_input_counters(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "model": "claude-opus-4-5",
                    "usage": {"input_tokens": 1000,
                              "cache_creation_input_tokens": 2000,
                              "cache_read_input_tokens": 97_000}},
    }) + "\n", encoding="utf-8")
    tokens, model = stop.latest_usage(t)
    assert tokens == 100_000
    assert "opus" in model


def test_latest_usage_skips_subagent_turns(tmp_path):
    """A subagent carries its own small context; counting it silenced the hook."""
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join([_turn(400_000), _turn(30_000, sidechain=True)]) + "\n",
                 encoding="utf-8")
    assert stop.latest_usage(t)[0] == 400_000


def test_latest_usage_on_a_missing_file_is_zero(tmp_path):
    assert stop.latest_usage(tmp_path / "nope.jsonl") == (0, "")


# --- staying quiet ---------------------------------------------------------

def test_a_fresh_handoff_after_the_last_nag_silences_the_hook(tmp_path):
    d = tmp_path / "handoff"
    d.mkdir()
    marker_time = time.time() - 300           # nagged five minutes ago
    note = d / "NOW-parser.md"
    note.write_text("handoff", encoding="utf-8")
    assert stop.handoff_written_since(d, marker_time) is True


def test_a_handoff_older_than_the_last_nag_does_not_silence_it(tmp_path):
    d = tmp_path / "handoff"
    d.mkdir()
    note = d / "NOW-parser.md"
    note.write_text("handoff", encoding="utf-8")
    marker_time = time.time() + 60            # nagged after the note was written
    assert stop.handoff_written_since(d, marker_time) is False


def test_no_marker_means_nothing_can_silence_the_hook(tmp_path):
    d = tmp_path / "handoff"
    d.mkdir()
    (d / "NOW-parser.md").write_text("handoff", encoding="utf-8")
    assert stop.handoff_written_since(d, None) is False


def test_reason_text_names_the_line_it_crossed(tmp_path):
    soft = stop.reason_text("soft", 100_000, "claude-sonnet-4", 90_000, 150_000,
                            1, tmp_path)
    hard = stop.reason_text("hard", 400_000, "claude-sonnet-4", 90_000, 150_000,
                            3, tmp_path)
    assert "soft line" in soft and "natural stopping point" in soft
    assert "hard line" in hard and "NOW" in hard
    assert "nag #3" in hard


# --- the session-start track list -----------------------------------------

def test_track_list_names_each_live_track(tmp_path):
    d = tmp_path / "handoff"
    d.mkdir()
    (d / "NOW-parser.md").write_text("x", encoding="utf-8")
    (d / "NOW-billing.md").write_text("x", encoding="utf-8")
    lines = "\n".join(start.build_lines(d))
    assert "parser" in lines and "billing" in lines


def test_track_list_ignores_stale_tracks(tmp_path):
    d = tmp_path / "handoff"
    d.mkdir()
    old = d / "NOW-abandoned.md"
    old.write_text("x", encoding="utf-8")
    ancient = time.time() - 40 * 86400
    import os
    os.utime(old, (ancient, ancient))
    assert start.build_lines(d) == []


def test_track_list_warns_about_dated_files(tmp_path):
    d = tmp_path / "handoff"
    d.mkdir()
    (d / "NOW-parser.md").write_text("x", encoding="utf-8")
    (d / "2026-01-04-parser-notes.md").write_text("x", encoding="utf-8")
    lines = "\n".join(start.build_lines(d))
    assert "WARNING" in lines
    assert "2026-01-04-parser-notes.md" in lines


def test_missing_handoff_directory_is_silent(tmp_path):
    assert start.build_lines(tmp_path / "nope") == []
