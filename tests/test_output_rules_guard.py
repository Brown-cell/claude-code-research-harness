"""Tests for hooks/output_rules_guard.py.

Two things are checked here, and they are different:

  * that each kind of rule stops a message that breaks it and lets through one
    that does not -- the check working;
  * that a broken rule table stops the turn instead of quietly passing -- the
    check refusing to fail silent, which is the property an earlier version of
    this code did not have.

The shipped example table is also loaded, so a rule whose net is too wide
cannot be committed without a test going red.
"""
import importlib.util
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD = ROOT / "hooks" / "output_rules_guard.py"
EXAMPLE_RULES = ROOT / "rules" / "output_rules.example.json"


def _load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load(GUARD)


# --- helpers ---------------------------------------------------------------

def write_transcript(tmp_path, *messages):
    """A minimal JSONL transcript: one assistant message per argument."""
    path = tmp_path / "transcript.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for text in messages:
            fh.write(json.dumps({
                "type": "assistant",
                "message": {"role": "assistant",
                            "content": [{"type": "text", "text": text}]},
            }) + "\n")
    return path


def write_rules(tmp_path, rules, name="rules.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"rules": rules}), encoding="utf-8")
    return path


def run_guard(rules, transcript, env_extra=None):
    """Run the hook the way the harness does. Returns (exit code, stderr)."""
    import os
    env = dict(os.environ)
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, str(GUARD), "--rules", str(rules),
         "--transcript", str(transcript)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return proc.returncode, proc.stderr


DEFINE_RULE = {"name": "p95", "kind": "define", "pattern": r"\bp95\b",
               "gloss": "the 95th percentile"}
FORBID_RULE = {"name": "minimiser", "kind": "forbid",
               "pattern": r"(?i)\bsimply\s+run\b",
               "message": "write the command instead",
               "negative": "I ran it and it passed."}
REQUIRE_RULE = {"name": "unrun claim", "kind": "require",
                "pattern": r"\bshould work\b",
                "requires": r"unverified|untested",
                "message": "label it unverified",
                "negative": "The tests passed on the first attempt."}


# --- the three kinds -------------------------------------------------------

def test_define_violation_blocks(tmp_path):
    rules = write_rules(tmp_path, [DEFINE_RULE])
    t = write_transcript(tmp_path, "The p95 is 420ms.")
    code, err = run_guard(rules, t)
    assert code == 2
    assert "p95" in err


def test_define_glossed_on_the_spot_passes(tmp_path):
    rules = write_rules(tmp_path, [DEFINE_RULE])
    t = write_transcript(tmp_path, "The p95 (= the 95th percentile) is 420ms.")
    assert run_guard(rules, t)[0] == 0


def test_define_glossed_earlier_in_the_conversation_passes(tmp_path):
    """A term does not have to be re-glossed in every single message."""
    rules = write_rules(tmp_path, [DEFINE_RULE])
    t = write_transcript(tmp_path,
                         "The p95 (= the 95th percentile) is 420ms.",
                         "The p95 has come down to 380ms.")
    assert run_guard(rules, t)[0] == 0


def test_forbid_violation_blocks(tmp_path):
    rules = write_rules(tmp_path, [FORBID_RULE])
    t = write_transcript(tmp_path, "Simply run the migration and you are done.")
    code, err = run_guard(rules, t)
    assert code == 2
    assert "write the command instead" in err


def test_forbid_does_not_fire_inside_a_quotation(tmp_path):
    """You have to be able to quote a forbidden phrase to talk about the rule."""
    rules = write_rules(tmp_path, [FORBID_RULE])
    t = write_transcript(tmp_path,
                         'The old runbook says "simply run the migration", '
                         'and that is the line to delete.')
    assert run_guard(rules, t)[0] == 0


def test_require_violation_blocks(tmp_path):
    rules = write_rules(tmp_path, [REQUIRE_RULE])
    t = write_transcript(tmp_path, "This should work on the CI runner too.")
    code, err = run_guard(rules, t)
    assert code == 2
    assert "label it unverified" in err


def test_require_satisfied_passes(tmp_path):
    rules = write_rules(tmp_path, [REQUIRE_RULE])
    t = write_transcript(
        tmp_path, "This should work on the CI runner too -- unverified, "
                  "I only ran it locally.")
    assert run_guard(rules, t)[0] == 0


def test_require_holds_per_message(tmp_path):
    """Unlike define, a caveat given in an earlier message does not carry over."""
    rules = write_rules(tmp_path, [REQUIRE_RULE])
    t = write_transcript(tmp_path,
                         "This should work -- unverified, I have not run it.",
                         "It should work on the CI runner as well.")
    assert run_guard(rules, t)[0] == 2


def test_clean_message_passes_all_kinds(tmp_path):
    rules = write_rules(tmp_path, [DEFINE_RULE, FORBID_RULE, REQUIRE_RULE])
    t = write_transcript(tmp_path, "I ran the suite: 41 passed, 0 failed.")
    assert run_guard(rules, t)[0] == 0


# --- refusing to fail silent ----------------------------------------------

def test_broken_json_blocks(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text('{"rules": [ {"name": "x",} ]}', encoding="utf-8")
    t = write_transcript(tmp_path, "anything at all")
    code, err = run_guard(bad, t)
    assert code == 2
    assert "not valid JSON" in err


def test_missing_rule_table_blocks(tmp_path):
    t = write_transcript(tmp_path, "anything at all")
    code, err = run_guard(tmp_path / "does_not_exist.json", t)
    assert code == 2
    assert "not found" in err


def test_missing_rule_table_can_be_made_optional(tmp_path):
    t = write_transcript(tmp_path, "anything at all")
    code, _ = run_guard(tmp_path / "does_not_exist.json", t,
                        {"HARNESS_RULES_OPTIONAL": "1"})
    assert code == 0


def test_bad_regex_blocks(tmp_path):
    rules = write_rules(tmp_path, [{"name": "x", "pattern": "([unclosed"}])
    t = write_transcript(tmp_path, "anything at all")
    code, err = run_guard(rules, t)
    assert code == 2
    assert "pattern" in err


def test_forbid_without_negative_blocks(tmp_path):
    rules = write_rules(tmp_path, [{"name": "x", "kind": "forbid",
                                    "pattern": "widget", "message": "no"}])
    t = write_transcript(tmp_path, "nothing relevant here")
    code, err = run_guard(rules, t)
    assert code == 2
    assert "negative" in err


def test_negative_that_fires_blocks(tmp_path):
    """The admission test: an example that must not fire, but does."""
    rules = write_rules(tmp_path, [{"name": "x", "kind": "forbid",
                                    "pattern": "widget", "message": "no",
                                    "negative": "this widget is fine"}])
    t = write_transcript(tmp_path, "nothing relevant here")
    code, err = run_guard(rules, t)
    assert code == 2
    assert "too wide" in err


def test_unknown_kind_blocks(tmp_path):
    rules = write_rules(tmp_path, [{"name": "x", "kind": "encourage",
                                    "pattern": "widget"}])
    t = write_transcript(tmp_path, "nothing relevant here")
    code, err = run_guard(rules, t)
    assert code == 2
    assert "unknown kind" in err


# --- fail-open on the harness side ----------------------------------------

def test_absent_transcript_passes(tmp_path):
    """A transcript we cannot read is the harness misbehaving, not the author."""
    rules = write_rules(tmp_path, [DEFINE_RULE])
    code, _ = run_guard(rules, tmp_path / "no_such_transcript.jsonl")
    assert code == 0


def test_transcript_with_no_assistant_message_passes(tmp_path):
    rules = write_rules(tmp_path, [DEFINE_RULE])
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "user",
                             "message": {"role": "user", "content": "p95?"}}) + "\n",
                 encoding="utf-8")
    assert run_guard(rules, t)[0] == 0


# --- the shipped example table --------------------------------------------

def test_example_rule_table_is_admissible():
    """Every negative in the shipped table must stay silent, and every
    forbid/require line must have one. This is the regression test that stops a
    too-wide net from being committed."""
    rules, err = guard.load_rules(EXAMPLE_RULES)
    assert err is None, err
    assert len(rules) >= 6
    kinds = [r.get("kind", "define") for r in rules]
    for kind in ("define", "forbid", "require"):
        assert kinds.count(kind) >= 2, f"expected at least two {kind} rules"


def test_example_table_catches_a_real_violation(tmp_path):
    t = write_transcript(tmp_path, "Just run the migration; it should work.")
    code, err = run_guard(EXAMPLE_RULES, t)
    assert code == 2
    assert "minimising words" in err
