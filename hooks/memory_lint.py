#!/usr/bin/env python
"""SessionStart hook: audit the memory index. Detective, not corrective.

WHY THIS EXISTS
---------------
This started as a hand-written review of a memory directory that had grown for
months. Reading the whole thing with fresh eyes turned up three kinds of rot,
and all three were mechanical:

  * a durable fact that had been superseded, with both versions still present
    and nothing saying which one was current;
  * an index line describing a file whose content had moved on without it (the
    index still promised the old behaviour);
  * a hard-won gotcha sitting in a file that nothing linked to any more, so it
    would never be read again.

None of those needed judgement to *find*. They needed judgement to *fix*. So
this hook finds them and stops there: it prints, a human or a session decides.
It says nothing at all when the index is clean, which is what makes it possible
to leave running on every session start.

Silence a false positive by putting the string 'lint-ok' anywhere on the index
line. That is deliberately the crudest possible mechanism, an escape hatch
that costs one word is an escape hatch people actually use, instead of turning
the whole hook off.

WHAT IT CANNOT DO
-----------------
Contradictions between two memory files, or a durable fact buried in a file
about something else, cannot be found by a machine. That is the periodic
read-it-all-with-fresh-eyes review, and the last bucket below is the reminder
to do it.

WHERE MEMORY LIVES
------------------
  1. $HARNESS_MEMORY_DIR if set.
  2. Otherwise ~/.claude/projects/<slug>/memory, where <slug> is the project
     path with every character outside [A-Za-z0-9] replaced by '-'. That is
     how Claude Code names a project's own directory, so this guess lands on
     the right one without configuration.

GIT IS OPTIONAL
---------------
If the memory directory is a git repository, two extra checks come alive:
index drift (a file committed well after the index line that describes it) and
dormancy by commit date. Without git, dormancy falls back to file modification
time and drift is skipped, it needs per-line history, which only blame has.
"""
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

PREFIXES = ("user_", "feedback_", "project_", "reference_")
LINK = re.compile(r"\]\(([^)#]+\.md)\)")
DEADLINE_KW = re.compile(r"deadline|expires?|expiry|due\b|renew", re.I)
DATE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

DRIFT_DAYS = 3      # file committed this much later than its index line => drift
DORMANT_DAYS = 45   # untouched this long while filed under an active section
REVIEW_DAYS = 35    # cadence of the full read-it-all review
SIZE_LINES, SIZE_BYTES = 110, 18000   # index budget: it is injected every session


def memory_dir():
    env = os.environ.get("HARNESS_MEMORY_DIR")
    if env:
        return Path(env)
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(project).resolve()))
    return Path.home() / ".claude" / "projects" / slug / "memory"


def active_sections():
    env = os.environ.get("HARNESS_MEMORY_ACTIVE_SECTIONS")
    if env:
        return {s.strip() for s in env.split(",") if s.strip()}
    return {"Active", "In progress", "Projects", "Current"}


class Repo:
    """git access that degrades to nothing when there is no repository."""

    def __init__(self, root):
        self.root = root
        self.ok = False
        try:
            r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                               cwd=root, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            self.ok = r.returncode == 0 and r.stdout.strip() == "true"
        except (OSError, ValueError):
            self.ok = False

    def _git(self, *args):
        if not self.ok:
            return ""
        try:
            r = subprocess.run(["git", *args], cwd=self.root, capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return r.stdout if r.returncode == 0 else ""

    def file_commits(self):
        """filename -> (last commit unix ts, commit hash), in one git call."""
        out = self._git("log", "--format=%x01%H %ct", "--name-only")
        ts_map = {}
        h = ts = None
        for line in out.splitlines():
            if line.startswith("\x01"):
                parts = line[1:].split()
                if len(parts) != 2:
                    continue
                h, ts = parts[0], int(parts[1])
            elif line.strip() and line.strip() not in ts_map:
                ts_map[line.strip()] = (ts, h)
        return ts_map

    def index_line_times(self, name="MEMORY.md"):
        """line number in the index -> unix ts of the commit that wrote it."""
        out = self._git("blame", "--line-porcelain", "--", name)
        ts, cur, lineno = {}, None, 0
        for line in out.splitlines():
            m = re.match(r"^[0-9a-f]{40} \d+ (\d+)", line)
            if m:
                lineno = int(m.group(1))
            elif line.startswith("committer-time "):
                cur = int(line.split()[1])
            elif line.startswith("\t"):
                ts[lineno] = cur
        return ts


def parse_expired_deadline(line, today):
    """A past date on a line that talks about a deadline. None otherwise."""
    if not DEADLINE_KW.search(line):
        return None
    for m in DATE_ISO.finditer(line):
        try:
            d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if d < today:
            return d
    return None


def main():
    mem = memory_dir()
    index = mem / "MEMORY.md"
    archive = mem / "MEMORY_ARCHIVE.md"
    ack = mem / ".lint_ack"                  # lines: "<file.md> <commit hash>"
    last_review = mem / ".last_full_review"  # one ISO date

    if not mem.exists():
        return 0            # no memory directory configured: nothing to audit
    if not index.exists():
        print(f"[memory] MEMORY.md MISSING, the memory index is gone ({mem})")
        return 0

    today = datetime.date.today()
    idx_lines = index.read_text(encoding="utf-8").splitlines()
    arch_text = archive.read_text(encoding="utf-8") if archive.exists() else ""
    linked = set(LINK.findall("\n".join(idx_lines))) | set(LINK.findall(arch_text))
    on_disk = {f.name for f in mem.glob("*.md") if f.name.startswith(PREFIXES)}

    repo = Repo(mem)
    ts_map = repo.file_commits()
    line_ts = repo.index_line_times()
    acks = set()
    if ack.exists():
        for ln in ack.read_text(encoding="utf-8").splitlines():
            parts = ln.split()
            if len(parts) == 2:
                acks.add((parts[0], parts[1]))

    dead = [f"  {t}" for t in sorted(linked)
            if t.endswith(".md") and not (mem / t).exists()]
    orphans = [f"  {f}" for f in sorted(on_disk - linked)]

    live = active_sections()
    expired, drift, dormant = [], [], []
    section = ""
    for i, line in enumerate(idx_lines, 1):
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if "lint-ok" in line:
            continue
        d = parse_expired_deadline(line, today)
        if d:
            expired.append(f"  L{i} ({d.isoformat()}): {line.strip()[:80]}")
        m = LINK.search(line)
        if not m:
            continue
        target = m.group(1)
        f_ts, f_hash = ts_map.get(target, (None, None))
        if f_ts is None:
            p = mem / target
            f_ts = int(p.stat().st_mtime) if p.exists() else None
        l_ts = line_ts.get(i)
        if f_ts and l_ts and f_ts - l_ts > DRIFT_DAYS * 86400 \
                and (target, f_hash) not in acks:
            drift.append(f"  {target} (file changed "
                         f"{(f_ts - l_ts) // 86400}d after its index line)")
        if f_ts and section in live:
            age = (today - datetime.date.fromtimestamp(f_ts)).days
            if age > DORMANT_DAYS:
                dormant.append(f"  {target} (untouched {age}d, section: {section})")

    oversize = []
    n_bytes = index.stat().st_size
    if len(idx_lines) > SIZE_LINES or n_bytes > SIZE_BYTES:
        oversize.append(f"  MEMORY.md = {len(idx_lines)} lines / {n_bytes} B "
                        f"(budget {SIZE_LINES} / {SIZE_BYTES})")

    review_due = []
    try:
        last = datetime.date.fromisoformat(
            last_review.read_text(encoding="utf-8").strip())
        if (today - last).days > REVIEW_DAYS:
            review_due.append(f"  last full review {last.isoformat()} "
                              f"({(today - last).days}d ago)")
    except (OSError, ValueError):
        review_due.append("  .last_full_review missing or unreadable")

    buckets = [
        (dead, "! dead link(s) in the index, file missing on disk:"),
        (orphans, "! orphan memory file(s), on disk but in neither index "
                  "(add a line, or archive it):"),
        (expired, "! expired deadline(s) in index text, check and update the "
                  "line (or mark it 'lint-ok'):"),
        (drift, "! index drift, the file changed after its index line was last "
                "touched; re-read the file, update the line, or acknowledge it "
                "in .lint_ack as '<file> <hash>':"),
        (dormant, "~ dormancy candidate(s) in active sections, consider "
                  "MEMORY_ARCHIVE.md (verify before archiving):"),
        (oversize, "~ index over its size budget, trim the one-liners, archive "
                   "the finished ones (progressive disclosure):"),
        (review_due, "~ full read-it-all memory review is DUE, when it is done, "
                     "write today's date into memory/.last_full_review:"),
    ]
    if not any(b for b, _ in buckets):
        return 0
    print("[memory] memory index audit (detective, non-blocking):")
    if not repo.ok:
        print("  (no git repository in the memory directory: drift check skipped, "
              "dormancy measured by file mtime)")
    for hits, header in buckets:
        if hits:
            print(header)
            print("\n".join(hits[:15]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
