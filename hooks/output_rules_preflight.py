#!/usr/bin/env python3
"""UserPromptSubmit hook: put the rules you actually broke this week in front of
you *before* you write, not after.

WHY THIS EXISTS
---------------
`output_rules_guard.py` is a **Stop** hook, so it lands after the message has
already been written. It detects; it does not deter. Measured over six days of
one setup's fire log, the top five rules rang 30, 27, 25, 25 and 14 times --
on six days out of six. The guard's own message says "if you hear the same
thing twice, add a line to the rule table", and the firing did not stop. The
problem was not a missing rule. The problem was that the rules arrive too late,
and the reader has already had to read one bad message every time.

Adding another rule would stop in the same place. What was needed was a change
of route: one page in front of "scold after writing" that says "here, before
you write". UserPromptSubmit is the only hook whose stdout lands in the model's
context, so it is the only pre-output route there is.

DESIGN
------
  * **Do not hand over everything.** Only the rules that were actually broken
    recently. A rule table only grows, so injecting all of it would bloat every
    single turn. What is handed over is "the ones you tripped on this week".
  * **It expires on its own.** A rule that has not fired for WINDOW_DAYS drops
    off the list. A rule you have fixed never keeps eating context, so the list
    stays short without anyone pruning it.
  * **It never blocks.** Always exit 0. An entrance hook that can break a
    conversation is indefensible. A broken rule table is already stopped by the
    Stop hook, so there is nothing to duplicate here.
  * **It does not read message text.** The fire log holds rule names and
    timestamps only, by design (see output_rules_guard.log_fires). This hook
    keeps that property.
"""
import collections
import datetime
import io
import json
import os
import pathlib
import sys

WINDOW_DAYS = 7      # a rule that does not fire for this long drops off the list
MIN_DAYS = 2         # separates a habit from a single bad day: two distinct days
MAX_RULES = 8        # this is injected every turn, so cap it
MAX_CHARS = 1600     # same reason; past this, keep the most frequent
MAX_MSG = 140        # one rule, one line. `message` fields are sometimes whole
                     # paragraphs; injecting those verbatim every turn makes the
                     # list something people skim past. The full text is printed
                     # by the Stop hook at the moment of the violation.


# NOTE: output_rules_guard.py resolves the same two paths with the same rules.
# If you change the convention here, change it there too.

def project_dir():
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return pathlib.Path(env)
    return pathlib.Path(__file__).resolve().parent.parent


def rules_path():
    env = os.environ.get("HARNESS_RULES_FILE")
    if env:
        return pathlib.Path(env)
    return project_dir() / "rules" / "output_rules.json"


def log_path():
    env = os.environ.get("HARNESS_GUARD_LOG")
    if env:
        return pathlib.Path(env)
    return project_dir() / "logs" / "output_rules_fires.log"


def load_rules(store):
    """{name: rule}. Empty if unreadable -- this hook never stops anything."""
    if store is None or not store.exists():
        return {}
    try:
        doc = json.loads(store.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for r in doc.get("rules") or []:
        name = r.get("name")
        if name:
            out[name] = r
    return out


def recidivists(log, now=None):
    """[(name, fires, distinct days)] most frequent first."""
    now = now or datetime.datetime.now()
    cut = (now - datetime.timedelta(days=WINDOW_DAYS)).isoformat(timespec="seconds")
    fires = collections.Counter()
    days = collections.defaultdict(set)
    try:
        with io.open(log, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    ts, name = rec["ts"], rec["rule"]
                except Exception:
                    continue
                if ts >= cut:
                    fires[name] += 1
                    days[name].add(ts[:10])
    except OSError:
        return []
    out = [(n, c, len(days[n])) for n, c in fires.items() if len(days[n]) >= MIN_DAYS]
    out.sort(key=lambda t: (-t[1], t[0]))
    return out


def _short(s):
    s = " ".join((s or "").split())
    return s if len(s) <= MAX_MSG else s[:MAX_MSG - 1] + "..."


def line_for(rule, name, count, ndays):
    """One rule, one line. Say what to write -- do not scold."""
    kind = rule.get("kind", "define")
    hits = f"[{count}x / {ndays}d]"
    if kind == "define":
        gloss = _short(rule.get("gloss", ""))
        return (f"  {hits} if you use \"{name}\", gloss it on the spot: "
                f"\"{name} (= {gloss})\"")
    if kind == "forbid":
        return f"  {hits} do not use \"{name}\" -- {_short(rule.get('message', ''))}"
    return f"  {hits} if you write \"{name}\", {_short(rule.get('message', ''))}"


def build_note():
    log = log_path()
    if not log.exists():
        return ""
    store = rules_path()
    rules = load_rules(store)
    if not rules:
        return ""
    rows = [(n, c, d) for n, c, d in recidivists(log) if n in rules]
    if not rows:
        return ""

    lines = [f"[output rules] Rules you ACTUALLY broke in the last {WINDOW_DAYS} days. "
             f"Hold them while writing, not after:"]
    for name, count, ndays in rows[:MAX_RULES]:
        nxt = line_for(rules[name], name, count, ndays)
        if sum(len(x) for x in lines) + len(nxt) > MAX_CHARS:
            break
        lines.append(nxt)
    lines.append(f"  (this list disappears on its own once a rule stops firing; "
                 f"the rules themselves are in {store})")
    return "\n".join(lines)


def main():
    try:
        json.load(sys.stdin)          # input is unused, but read it to completion
    except Exception:
        pass
    try:
        note = build_note()
    except Exception:
        note = ""                     # an entrance hook never breaks a conversation
    if note:
        sys.stdout.write(note + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
