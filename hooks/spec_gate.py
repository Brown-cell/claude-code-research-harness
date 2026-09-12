#!/usr/bin/env python3
"""PreToolUse hook on the Agent tool: refuse a delegation whose spec is not
written under the ten fixed headings.

The headings and the reasoning are in docs/delegation_protocol.md, section 4.
The short version: I counted 122 delegation prompts from my own transcripts
and found six roles written under 49 different heading names. The one role
that had a single consistent name was the one I had added as a named field.
Only a field with a name travels to the next job, and once the vocabulary is
closed a machine can check it. This is that machine.

Three checks, all on the prompt text:

  1. every heading is present, spelled exactly, in this order;
  2. no heading is blank. A field with nothing to say gets one of the reserved
     words (any / defaults / none / -), because a blank cannot be told apart
     from an omission;
  3. the gate only applies to the agent types you name. Exploratory or
     one-line delegations do not need a spec.

Override: put a line `spec-gate: ok <reason>` anywhere in the prompt. The
reason is required, and the override is deliberately visible in the transcript.

Environment:
  HARNESS_SPEC_GATE_AGENTS   comma-separated subagent types to check
                             (default: build,exec). "*" checks every Agent call.

Inspection entry point:
  python hooks/spec_gate.py --prompt spec.md
Same code path, same exit code as the live hook.
"""
import argparse
import json
import os
import re
import sys

try:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HEADINGS = [
    "Read first",
    "Background",
    "Task",
    "Discretion",
    "Acceptance",
    "Write paths",
    "Prohibited",
    "Tool budget",
    "Failure mode",
    "Reporting",
]
RESERVED = {"any", "defaults", "none", "-"}
OVERRIDE = re.compile(r"^[ \t]*spec-gate:[ \t]*ok\b[ \t]*(.*)$", re.I | re.M)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def core(heading):
    """Drop an annotation after a colon or an opening bracket."""
    return re.split(r"[:(\[]", heading, maxsplit=1)[0].strip()


def split(text):
    """[(heading, body)] at the depth where the fixed headings appear.

    Depth is not a rule; specs in the wild use '#' and '##' both. The depth
    that the fixed names actually appear at is taken as the block level, and
    deeper headings are treated as content.
    """
    lines = text.splitlines()
    heads = []
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))
    depths = [d for _, d, h in heads if core(h) in HEADINGS]
    if not depths:
        return []
    level = min(set(depths), key=lambda d: (-depths.count(d), d))
    marks = [(i, h) for i, d, h in heads if d <= level]
    blocks = []
    for k, (i, h) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        blocks.append((core(h), "\n".join(lines[i + 1:end]).strip()))
    return blocks


def check(text):
    """Return a list of problems. Empty means the spec passes."""
    problems = []
    blocks = split(text)
    names = [h for h, _ in blocks]
    missing = [h for h in HEADINGS if h not in names]
    if missing:
        problems.append("missing: " + " / ".join(missing))
    present = [h for h in names if h in HEADINGS]
    order = [HEADINGS.index(h) for h in present]
    if order != sorted(order):
        problems.append("out of order: " + " > ".join(present))
    for h, body in blocks:
        if h in HEADINGS and not body:
            problems.append(f"blank: {h} (write one of {', '.join(sorted(RESERVED))})")
    return problems


def report(problems, sub):
    lines = [f"[spec-gate] the delegation to '{sub}' is not written under the ten headings."]
    lines += ["    " + p for p in problems]
    lines += [
        "  Use these strings, in this order, at one heading depth:",
        "    " + " / ".join(HEADINGS),
        "  A field with nothing to say gets one of: " + ", ".join(sorted(RESERVED)) + ".",
        "  To send it as is, add a line 'spec-gate: ok <reason>' to the prompt.",
        "  (mechanism: hooks/spec_gate.py; why: docs/delegation_protocol.md section 4)",
    ]
    return "\n".join(lines)


def gated(sub):
    wanted = os.environ.get("HARNESS_SPEC_GATE_AGENTS", "build,exec")
    if wanted.strip() == "*":
        return True
    return sub in {w.strip() for w in wanted.split(",") if w.strip()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prompt", help="check this file instead of hook JSON on stdin")
    args = ap.parse_args(argv)

    if args.prompt:
        with open(args.prompt, encoding="utf-8") as fh:
            text = fh.read()
        sub = "(file)"
    else:
        try:
            data = json.load(sys.stdin)
        except Exception:
            return 0
        if data.get("tool_name") not in ("Agent", "Task"):
            return 0
        tool_input = data.get("tool_input") or {}
        sub = tool_input.get("subagent_type") or "general-purpose"
        if not gated(sub):
            return 0
        text = tool_input.get("prompt") or ""

    m = OVERRIDE.search(text)
    if m:
        if m.group(1).strip():
            return 0
        print("[spec-gate] 'spec-gate: ok' needs a reason after it.", file=sys.stderr)
        return 2

    problems = check(text)
    if not problems:
        return 0
    print(report(problems, sub), file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
