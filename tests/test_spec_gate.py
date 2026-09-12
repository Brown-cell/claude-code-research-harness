"""Tests for hooks/spec_gate.py: the ten headings, their order, blanks, the
reserved words, the agent-type filter and the visible override."""
import importlib.util
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE = ROOT / "hooks" / "spec_gate.py"


def _load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load(GATE)

GOOD = """# Read first
docs/why.md
# Background
We need a smaller README.
# Task
Rewrite the first section.
# Discretion
any
# Acceptance
pytest tests/ is green.
# Write paths
README.md (overwrite)
# Prohibited
none
# Tool budget
Read 3 files, write 1, 20 turns.
# Failure mode
Write section by section.
# Reporting
defaults
"""


def run(payload, env=None):
    full = dict(**{"PYTHONUTF8": "1"}, **(env or {}))
    import os
    full = {**os.environ, **full}
    return subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                          capture_output=True, text=True, env=full)


def agent_call(prompt, sub="build"):
    return {"tool_name": "Agent",
            "tool_input": {"subagent_type": sub, "prompt": prompt}}


def test_complete_spec_passes():
    assert gate.check(GOOD) == []


def test_missing_heading_is_named():
    text = GOOD.replace("# Failure mode\nWrite section by section.\n", "")
    problems = gate.check(text)
    assert any("missing: Failure mode" in p for p in problems)


def test_order_is_enforced():
    text = GOOD.replace("# Task\nRewrite the first section.\n", "")
    text = text.replace("# Reporting\n", "# Task\nRewrite the first section.\n# Reporting\n")
    problems = gate.check(text)
    assert any(p.startswith("out of order") for p in problems)


def test_blank_field_is_rejected_but_reserved_word_passes():
    text = GOOD.replace("# Discretion\nany\n", "# Discretion\n\n")
    problems = gate.check(text)
    assert any(p.startswith("blank: Discretion") for p in problems)
    assert gate.check(GOOD.replace("# Discretion\nany\n", "# Discretion\n-\n")) == []


def test_heading_depth_and_annotations_are_free():
    text = "\n".join(
        ("## " + line[2:] if line.startswith("# ") else line) for line in GOOD.splitlines())
    text = text.replace("## Task", "## Task: what to do")
    assert gate.check(text) == []


def test_live_hook_blocks_build_and_ignores_other_agents():
    bad = agent_call("please do the thing")
    assert run(bad).returncode == 2
    assert "[spec-gate]" in run(bad).stderr
    assert run(agent_call("please do the thing", sub="Explore")).returncode == 0
    assert run(agent_call(GOOD)).returncode == 0


def test_override_needs_a_reason():
    with_reason = agent_call("spec-gate: ok one-line lookup, no writes\nfind the config file")
    assert run(with_reason).returncode == 0
    without = agent_call("spec-gate: ok\nfind the config file")
    assert run(without).returncode == 2


def test_star_gates_every_agent():
    r = run(agent_call("do it", sub="Explore"), env={"HARNESS_SPEC_GATE_AGENTS": "*"})
    assert r.returncode == 2


def test_unreadable_stdin_fails_open():
    import os
    r = subprocess.run([sys.executable, str(GATE)], input="not json",
                       capture_output=True, text=True, env={**os.environ, "PYTHONUTF8": "1"})
    assert r.returncode == 0
