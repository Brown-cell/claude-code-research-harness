#!/usr/bin/env python3
"""SessionStart hook: list the live tracks, so a fresh thread picks the right
handoff instead of being handed whichever file happened to be newest.

WHY IT IS A LIST AND NOT A POINTER
----------------------------------
The first version of this printed one file: the most recently modified handoff.
Measured across several hundred transcripts, of 259 such hints only 41% were
followed, and 16% were ignored while the session went and opened a *different*
handoff, that is, the hint had pointed at the wrong track. Running several
threads in parallel is the normal case, so modification time can never key this
correctly. There is no ranking that fixes it; the premise was wrong.

So the scheme changed: one living file per track, `NOW-<track>.md`, overwritten
in place. Listing the directory then *is* the track list, and choosing is handed
back to the reader, who is the only one who knows which track this thread is.

The dated-file warning exists because the previous convention (one dated file
per handoff) had grown to a couple of hundred files with no way to tell which
was current. If one shows up again, say so rather than ignoring it silently.
its content is otherwise lost to the next thread.

CONFIGURATION
-------------
  HARNESS_HANDOFF_DIR   default: $CLAUDE_PROJECT_DIR/handoff
"""
import os
import pathlib
import re
import sys
import time

FRESH_DAYS = 14   # older than this and the track is probably not live
MAX_TRACKS = 5    # this is injected into every session start; keep it short
MAX_STRAY = 4
DATED = re.compile(r"^\d{4}-\d{2}-\d{2}")


def handoff_dir():
    env = os.environ.get("HARNESS_HANDOFF_DIR")
    if env:
        return pathlib.Path(env)
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return pathlib.Path(project) / "handoff"


def age_label(seconds):
    hours = seconds / 3600
    if hours < 48:
        return f"{int(hours)}h ago"
    return f"{int(hours / 24)}d ago"


def build_lines(directory, now=None):
    now = now or time.time()
    if not directory.exists():
        return []
    files = [f for f in directory.glob("*.md") if f.is_file()]
    live = sorted(
        (f for f in files
         if f.name.startswith("NOW-")
         and (now - f.stat().st_mtime) < FRESH_DAYS * 86400),
        key=lambda f: f.stat().st_mtime, reverse=True)[:MAX_TRACKS]
    stray = sorted((f for f in files if DATED.match(f.name)),
                   key=lambda f: f.stat().st_mtime, reverse=True)[:MAX_STRAY]

    out = []
    if live:
        out.append("[handoff] live tracks, one file per track, updated in place "
                   "(newest first):")
        for f in live:
            track = f.name[len("NOW-"):-len(".md")]
            out.append(f"  {track:<24} {age_label(now - f.stat().st_mtime):<9} {f}")
        out.append("Open the one this session continues, and check its 'updated:' "
                   "line before trusting it.")
        out.append("Unrelated new task: ignore all of them. Track list stale or "
                   "wrong: it is just this directory.")
    if stray:
        out.append("[handoff] WARNING: dated handoff file(s) in the handoff root: "
                   + ", ".join(f.name for f in stray))
        out.append("  The scheme is handoff/NOW-<track>.md, updated in place.")
        out.append("  Fold each into its NOW file, then move it to handoff/archive/.")
    return out


def main():
    lines = build_lines(handoff_dir())
    if lines:
        sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
