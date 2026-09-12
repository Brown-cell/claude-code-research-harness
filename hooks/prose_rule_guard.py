#!/usr/bin/env python3
"""PostToolUse nudge: writing a rule as prose is the weakest enforcement there is.

The case that settled it: a rule about file encoding was written into an
operational guardrails document three separate times, and broken anyway, once
silently (a script exited 0 and did nothing), once loudly (a scheduled task died
immediately). Three paragraphs, zero enforcement. Prose has no enforcement
surface. Code does.

So this hook fires at the exact moment prose is being written into a document
whose job is to change future behaviour, and asks the one question that matters:
can this be checked by a machine? It never blocks, some rules genuinely cannot
be checked, and saying so out loud is a legitimate answer. It just refuses to
let "I wrote it down" pass unexamined. Once per file per session.

The general rule behind it: the second time the same kind of mistake happens,
build a mechanism instead of writing another paragraph.
"""
import datetime
import json
import os
import pathlib
import re
import sys

TTL_SEC = 6 * 3600

# Operational rule documents: places where a line is meant to change future
# behaviour. Adjust to taste, this is the one part that is local convention.
RULE_DOC = re.compile(
    r"(prompts[\\/][^\\/]*\.md"
    r"|docs[\\/][^\\/]*(?:protocol|standard|convention|rules?)[^\\/]*\.md"
    r"|CLAUDE\.md"
    r"|AGENTS\.md"
    r"|[^\\/]*GUARDRAILS?[^\\/]*\.md"
    r"|[^\\/]*CHECKLIST[^\\/]*\.md)$", re.I)

# Durable feedback belongs in the memory directory by design, that IS the
# right home for a rule a machine cannot check, so firing there would be noise
# rather than signal. (Learned the hard way: this hook's first live shot was a
# memory file whose name merely contained the word "guardrails".)
EXCLUDE = re.compile(r"[\\/]memory[\\/]", re.I)

MSG = """[prose-rule] {name}
  You are writing a rule as prose. Prose has no enforcement surface, the file
  encoding rule sat in a guardrails document three times and was violated anyway.
  Before you finish this edit, answer one question and act on it:

    Can this rule be checked by a machine?
      yes -> build it (a PostToolUse hook, a lint, a test, a schema, one more
             line in the output rule table). If the change touches files your
             harness protects, ask the user to unlock them from their own
             terminal. Then keep only a one-line pointer to the mechanism in
             the document.
      no  -> keep the prose, and say plainly in your reply that it is
             unenforced, so the user knows what they are relying on.

  Default to the structural fix every time you notice a trap, do not settle
  for another paragraph.
  (mechanism: hooks/prose_rule_guard.py)"""


def stamp_path():
    env = os.environ.get("HARNESS_PROSE_STAMP")
    if env:
        return pathlib.Path(env)
    return pathlib.Path(__file__).resolve().parent / ".prose_rule_seen.json"


def seen(path):
    """True if this file was already nudged within TTL_SEC. Records the visit."""
    stamp = stamp_path()
    now = datetime.datetime.now().timestamp()
    try:
        data = json.loads(stamp.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data = {k: v for k, v in data.items() if now - v < TTL_SEC}
    key = str(path).lower()
    hit = key in data
    data[key] = now
    try:
        stamp.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
    return hit


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return 0
    raw = (data.get("tool_input") or {}).get("file_path") or ""
    if not raw or not RULE_DOC.search(raw) or EXCLUDE.search(raw):
        return 0
    path = pathlib.Path(raw)
    if seen(path):
        return 0
    print(MSG.format(name=path.name), file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
