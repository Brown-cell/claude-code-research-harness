#!/usr/bin/env python3
"""Stop hook: a two-tier context handoff trigger.

  Soft line -- ask for a handoff only if the work is at a natural stopping point.
  Hard line -- ask unconditionally, before auto-compaction degrades the thread.

WHY TWO LINES
-------------
Every turn re-reads the whole context, so one turn at context C costs roughly
0.1*C in cache reads before any work happens. Rebuilding a window costs the
session baseline plus the handoff, call it ~65k once. That means a 300k window
pays for a restart in under three turns, and a 150k window in under seven. The
soft line is where restarting has started to be cheaper if you are at a seam;
the hard line is where it is cheaper regardless.

One line would be worse than two. A single early line gets ignored because the
work is mid-flight; a single late line arrives after the expensive turns have
already been paid for.

WHY IT ESCALATES
----------------
In the setup this came from, the nag was measured being ignored up to seven
times in one session, while that session ran past 600k. Repeating yourself at
600k is not free -- the reminder itself is charged at the context that made it
necessary. So the marker file carries a count: after three ignored nags the
cooldown widens from 10 to 30 minutes and the wording gets blunter, instead of
paying full price to say the same thing forever.

WHY IT READS A BOUNDED TAIL
---------------------------
A transcript line can be several hundred kilobytes when an image is inlined.
Reading the last 300 lines the naive way had to materialise ~100MB and blew the
hook timeout on exactly the image-heavy sessions that cost the most -- so the
sessions that needed the nag most were the ones that never got it. Read a
bounded byte tail and scan it backwards.

Subagent turns are skipped (`isSidechain`). They carry their own small context
and their own model; counting them made the hook read a subagent's 30k instead
of the parent's 400k, and go quiet.

CONFIGURATION
-------------
  HANDOFF_SOFT / HANDOFF_HARD   override the thresholds (integers)
  HARNESS_HANDOFF_DIR           where handoff notes live
                                (default: $CLAUDE_PROJECT_DIR/handoff)
"""
import json
import os
import pathlib
import sys
import tempfile
import time

TAIL_BYTES = 12 * 1024 * 1024   # bounded tail of the transcript
MAX_LINES_SCANNED = 400         # candidate lines examined, newest first
DEFAULT_SOFT, DEFAULT_HARD = 90_000, 150_000

# Per-model lines. All three public models default to the same pair; the table
# exists so that when one model's window is the scarce quota -- a weekly cap, a
# more expensive tier -- you can tighten that one alone, e.g. ("opus": (70_000,
# 120_000)). Matching is a substring test against the model id in the
# transcript, because ids carry suffixes.
MODEL_LINES = {
    "opus":   (DEFAULT_SOFT, DEFAULT_HARD),
    "sonnet": (DEFAULT_SOFT, DEFAULT_HARD),
    "haiku":  (DEFAULT_SOFT, DEFAULT_HARD),
}

RECENT_HANDOFF_MIN = 30   # a handoff younger than this can silence the nag
COOLDOWN_MIN = 10         # normal gap between nags in one session
COOLDOWN_MIN_IGNORED = 30 # gap after the nag has been ignored this often
IGNORED_AFTER = 3


# --- pure decision functions (unit-tested in tests/test_handoff.py) --------

def lines_for(model, env=None):
    """(soft, hard) for this model, with environment overrides applied last."""
    env = os.environ if env is None else env
    soft, hard = DEFAULT_SOFT, DEFAULT_HARD
    m = (model or "").lower()
    for key, (s, h) in MODEL_LINES.items():
        if key in m:
            soft, hard = s, h
            break
    for name, current in (("HANDOFF_SOFT", "soft"), ("HANDOFF_HARD", "hard")):
        raw = env.get(name)
        if raw:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if current == "soft":
                soft = value
            else:
                hard = value
    return soft, hard


def tier(tokens, soft, hard):
    """'hard', 'soft' or None -- which line this context has crossed."""
    if tokens >= hard:
        return "hard"
    if tokens >= soft:
        return "soft"
    return None


def cooldown_minutes(nags):
    """How long to stay quiet after a nag, given how many were ignored."""
    return COOLDOWN_MIN_IGNORED if nags >= IGNORED_AFTER else COOLDOWN_MIN


def per_turn_cost(tokens):
    """Weighted tokens the next turn costs before any work happens (~0.1x)."""
    return round(tokens / 10_000)


# --- transcript ------------------------------------------------------------

def latest_usage(transcript_path):
    """(tokens, model) of the most recent non-subagent assistant turn."""
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
            blob = fh.read()
    except OSError:
        return 0, ""
    lines = blob.decode("utf-8", errors="replace").split("\n")

    scanned = 0
    for line in reversed(lines):
        if scanned >= MAX_LINES_SCANNED:
            break
        # Plain substring test, never a regex: do not scan a 600KB base64 blob.
        if len(line) < 40 or '"usage"' not in line:
            continue
        scanned += 1
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("isSidechain"):
            continue
        msg = rec.get("message") or {}
        usage = msg.get("usage") or {}
        if rec.get("type") != "assistant" or usage.get("input_tokens") is None:
            continue
        tokens = (int(usage.get("input_tokens") or 0)
                  + int(usage.get("cache_creation_input_tokens") or 0)
                  + int(usage.get("cache_read_input_tokens") or 0))
        return tokens, str(msg.get("model") or "")
    return 0, ""


# --- state -----------------------------------------------------------------

def handoff_dir():
    env = os.environ.get("HARNESS_HANDOFF_DIR")
    if env:
        return pathlib.Path(env)
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return pathlib.Path(project) / "handoff"


def marker_path(session_id):
    return pathlib.Path(tempfile.gettempdir()) / f"claude_handoff_{session_id}.marker"


def read_marker(marker):
    """(mtime or None, nag count)."""
    try:
        nags = int(marker.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        try:
            return marker.stat().st_mtime, 0
        except OSError:
            return None, 0
    try:
        return marker.stat().st_mtime, nags
    except OSError:
        return None, nags


def handoff_written_since(directory, since_ts, now=None):
    """True if a handoff note was written after the last nag and is still fresh.

    Gated on the marker time so that a *different* session's handoff cannot
    silence a session that has never been nagged.
    """
    now = now or time.time()
    if since_ts is None or not directory.exists():
        return False
    for f in directory.glob("*.md"):
        if f.name.startswith("_"):
            continue
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if mtime > since_ts and (now - mtime) < RECENT_HANDOFF_MIN * 60:
            return True
    return False


# --- message ---------------------------------------------------------------

def reason_text(kind, tokens, model, soft, hard, nags, directory):
    kt = round(tokens / 1000)
    price = (f"Each further turn in this window costs about "
             f"{per_turn_cost(tokens)}k weighted tokens before any work happens.")
    where = directory / "NOW-<track>.md"
    how = (f"Write it to {where} -- one file per track, overwritten in place. "
           f"Do not accumulate dated files: they grow into a pile with no way to "
           f"tell which one is current. If your harness can spawn a subagent that "
           f"inherits this conversation, have that subagent write it, so the "
           f"handoff's own text never lands in this window. Verify the file "
           f"exists and is non-trivial BEFORE you tell the user anything: if the "
           f"write failed and the user clears the thread on your word, the thread "
           f"is lost.")
    head = f"[handoff] context ~{kt}k tokens (model {model or 'unknown'}): "
    if kind == "hard":
        urgent = (f"This is nag #{nags} in this session and the window is still "
                  f"growing: stop accepting new work in it. " if nags >= 2 else "")
        return (f"{head}hard line ({hard}) exceeded. {urgent}{price} "
                f"Get a handoff written NOW. {how} Do this even if you are mid-task.")
    return (f"{head}soft line ({soft}) exceeded. {price} If the work just "
            f"completed is at a natural stopping point (one task segment done), "
            f"get a handoff written. {how} If you are still mid-task, do nothing "
            f"and simply end your turn.")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("stop_hook_active"):
        return 0
    transcript = data.get("transcript_path") or ""
    if not transcript or not os.path.exists(transcript):
        return 0

    tokens, model = latest_usage(transcript)
    soft, hard = lines_for(model)
    kind = tier(tokens, soft, hard)
    if kind is None:
        return 0

    marker = marker_path(data.get("session_id") or "unknown")
    marker_ts, nags = read_marker(marker)

    directory = handoff_dir()
    if handoff_written_since(directory, marker_ts):
        return 0        # this session already handed off; stay quiet

    now = time.time()
    if marker_ts and (now - marker_ts) < cooldown_minutes(nags) * 60:
        return 0
    nags += 1
    try:
        marker.write_text(str(nags), encoding="utf-8")
    except OSError:
        pass

    print(json.dumps({
        "decision": "block",
        "reason": reason_text(kind, tokens, model, soft, hard, nags, directory),
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
