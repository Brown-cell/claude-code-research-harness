#!/usr/bin/env python3
"""Stop hook: check the final assistant message against a table of output rules,
and refuse to end the turn if it breaks one.

WHY THIS EXISTS
---------------
The rule that started it was not about style. An assistant message said, in
effect: "this week's ratio is 2.09 -> 2.35, above the proven band of 1.25".
Every one of those words was defined inside a script the reader had never
opened. The reader's reply was: what are these numbers? Nothing here says.

A machine scan of several hundred session logs then turned up something worse:
of the cases where the user had to repeat an instruction, nearly all of the
instructions were *already written down* in a document that is injected into
every session. One had been recorded two minutes after the user gave it, and
was broken again four days later. Writing a rule down does not make it hold.
The only cases that actually stopped were the ones where the prose rule got
converted into a machine check the same day.

So this hook is deliberately not a lexicon for one topic. It is a generic
checker over a rule table, so that "the user said this twice" can be converted
into "one more line of JSON" in under a minute.

WHERE THE RULES LIVE
--------------------
`$CLAUDE_PROJECT_DIR/rules/output_rules.json` -- outside this directory on
purpose. In the setup this grew out of, a guard protects everything under the
hooks directory from being edited by the agent, so a rule table kept next to
the code would need a human to unlock it for every new line. Code is dangerous
and stays locked; data moves out where it can be edited the moment a rule is
learned.

THE THREE CHECKS
----------------
  define  -- if the term appears, it must be glossed on the spot (within
             NEAR characters) by a parenthesis containing "=". Already glossed
             earlier in the same conversation counts, so nothing has to be
             repeated every message.
  forbid  -- the term must not be used. `message` says what to write instead.
  require -- if `pattern` appears, `requires` must appear somewhere in the
             same message.

Demanding "a parenthesis containing =" rather than just "a parenthesis" is not
pedantry: the message that started all this had a parenthesis full of numbers
which was not a definition. Checking only for brackets would have let the
original accident through.

NEVER FAIL SILENT
-----------------
An earlier version returned an empty rule list when the table could not be
read, so a single misplaced comma disabled every rule with no warning. That is
the most dangerous way to fail, not the safest: a missing table and a table
with no rules looked identical. Now a missing table, a syntax error, a broken
regular expression or a `forbid`/`require` line with no `negative` all STOP the
turn, because the fix is in a file the agent can edit right now. Set
HARNESS_RULES_OPTIONAL=1 if you want a missing table to be allowed (useful
while installing, or for a repository that has not written its rules yet).

An unreadable transcript is different -- that is the harness misbehaving, not
the author -- so it stays fail-open.

INSPECTION ENTRY POINT
----------------------
    python hooks/output_rules_guard.py --transcript fake.jsonl
    python hooks/output_rules_guard.py --rules other.json --transcript fake.jsonl

Same code path, same exit codes as the live hook, so you can ask the guard what
it would say about a message instead of guessing. It writes no log line in
--transcript mode, so looking is free.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import sys

# Messages go to stderr, which the harness shows to the model. Force UTF-8:
# on a non-UTF-8 console Python follows the terminal's encoding, the text gets
# written in the local code page, and whoever reads it as UTF-8 sees mojibake.
# A complaint nobody can read is the same as no complaint at all.
try:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NEAR = 90               # how close "glossed on the spot" has to be, in characters
TAIL_BYTES = 4 * 1024 * 1024   # never re-read a whole long transcript
SCAN_CAP = 200_000      # per-message scan cap, so a pathological regex cannot run away
KINDS = ("define", "forbid", "require")


# --- paths -----------------------------------------------------------------
# NOTE: output_rules_preflight.py resolves the same two paths with the same
# rules. If you change the convention here, change it there too.

def project_dir():
    """The repository root. Claude Code sets CLAUDE_PROJECT_DIR for hooks;
    falling back to the parent of this file keeps the script runnable by hand."""
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


# --- rule table ------------------------------------------------------------

def load_rules(store):
    """Return (rules, error). A non-None error means the table is broken: stop.

    The point of this function is that it refuses to return an empty list on
    failure. An empty list cannot be told apart from "no rules configured".
    """
    if not store.exists():
        if os.environ.get("HARNESS_RULES_OPTIONAL") == "1":
            return [], None
        return [], (f"rule table not found: {store}\n"
                    f"    (set HARNESS_RULES_OPTIONAL=1 to allow this)")
    try:
        doc = json.loads(store.read_text(encoding="utf-8"))
    except Exception as e:                       # syntax error: do not go quiet
        return [], f"rule table is not valid JSON: {store}\n    {e}"
    rules = doc.get("rules")
    if rules is None:
        return [], f"rule table has no 'rules' key: {store}"
    if not isinstance(rules, list):
        return [], f"rule table's 'rules' is not a list: {store}"

    for i, r in enumerate(rules):
        tag = r.get("name") or f"#{i}"
        kind = r.get("kind", "define")
        if kind not in KINDS:
            return [], f"rule {tag}: unknown kind '{kind}' (one of {'/'.join(KINDS)})"
        try:
            r["_re"] = re.compile(r["pattern"])
        except (KeyError, re.error) as e:
            return [], f"rule {tag}: bad 'pattern' -- {e}"
        if kind == "require":
            try:
                r["_req"] = re.compile(r["requires"])
            except (KeyError, re.error) as e:
                return [], f"rule {tag}: bad 'requires' -- {e}"
        if kind in ("forbid", "require"):
            # Admission test for wide nets. This hook runs on every single
            # message, so a rule whose net is too wide is a landmine that
            # interrupts unrelated work every day. Requiring an example of a
            # sentence that must NOT fire makes that structural instead of
            # something a test suite might or might not cover.
            neg = r.get("negative")
            if not neg:
                return [], (f"rule {tag}: a {kind} rule needs 'negative' "
                            f"(an example sentence that must not fire)")
            for n in ([neg] if isinstance(neg, str) else neg):
                if violates(n, r) is not None:
                    return [], (f"rule {tag}: its own 'negative' fires. The net is "
                                f"too wide, or the example is wrong:\n    {n}")
    return rules, None


# --- transcript ------------------------------------------------------------

def assistant_texts(transcript_path):
    """Assistant message texts from a JSONL transcript, oldest first.

    Only the last TAIL_BYTES are read. A half line at the front fails to parse
    as JSON and is dropped on its own. If an old gloss falls out of the window
    the worst case is being asked to gloss the term once more -- the failure
    leans to the harmless side.
    """
    out = []
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()               # drop the truncated line
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msg = rec.get("message") or {}
                if msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if isinstance(content, str):
                    out.append(content)
                elif isinstance(content, list):
                    out.append("\n".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"))
    except OSError:
        pass
    return out


# --- the checks ------------------------------------------------------------

def is_defined(text, rule):
    """define: is the term glossed nearby, or present in a table row?"""
    name = re.escape(rule["name"])
    # Start from the detection pattern (often narrow, e.g. "ratio 2.09") and
    # also from the shape of a definition, "<term> (". Without the second one a
    # correctly glossed sentence may not match the narrow pattern at all, and
    # then "already glossed earlier" can never become true.
    starts = [m.end() for m in rule["_re"].finditer(text)]
    starts += [m.end() for m in re.finditer(name + r"(?=\s*\()", text)]
    for end in starts:
        tail = text[end:end + NEAR]
        if re.search(r"\([^)\n]*=[^)\n]*\)", tail):
            return True
    # A row of a table that names the term is a gloss in a different shape.
    if re.search(r"^\s*\|[^|\n]{0,24}" + name + r"[^|\n]{0,24}\|", text, re.M):
        return True
    return False


QUOTED = re.compile(
    r"```.*?```"            # fenced code block
    r"|`[^`\n]*`"           # inline code
    r"|\"[^\"\n]*\""        # double-quoted
    r"|'[^'\n]*'", re.S)    # single-quoted


def quoted_spans(text):
    """Ranges where a `forbid` rule does not fire.

    Found in real data: a forbidden word appeared inside a quotation of an
    existing plan. If a forbidden term cannot be quoted, you can no longer talk
    *about* the rule -- this docstring could not be written. "Forbid" means
    "do not use it as your own word", not "this string may never appear".
    """
    return [m.span() for m in QUOTED.finditer(text)]


def violates(text, rule):
    """Return a string saying how to fix it, or None if the text is fine."""
    text = text[:SCAN_CAP]
    kind = rule.get("kind", "define")
    hit = rule["_re"].search(text)
    if kind == "forbid":
        if hit:
            spans = quoted_spans(text)
            for m in rule["_re"].finditer(text):
                if not any(s <= m.start() < e for s, e in spans):
                    return rule.get("message", "do not use this term")
        return None
    if kind == "require":
        if hit and not rule["_req"].search(text):
            return rule.get("message", f"{rule['requires']} is required")
        return None
    # define
    if hit and not is_defined(text, rule):
        return (f"write it as \"{rule['name']} (= {rule.get('gloss', '')})\" "
                f"the first time it appears")
    return None


def log_fires(names, path):
    """Append the names of the rules that fired. Never the text.

    This used to keep 40 characters of context on each side, which made the log
    a path for sensitive sentences to leak into a file nobody was watching. The
    only thing worth knowing here is which rule rings how often -- that is what
    tells you later whether a rule is an unfixed habit or a net that is too wide.
    """
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for n in names:
                fh.write(json.dumps({"ts": ts, "rule": n}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def judge(texts, rules):
    """Return [(rule name, how to fix)] for the last message in `texts`."""
    if not texts:
        return []
    last, earlier = texts[-1], texts[:-1]
    bad = []
    for r in rules:
        fix = violates(last, r)
        if fix is None:
            continue
        # "already glossed in this conversation" is a concession for `define`
        # only. `forbid` and `require` have to hold message by message: having
        # written the caveat once earlier does not license dropping it now.
        if r.get("kind", "define") == "define" and any(is_defined(e, r) for e in earlier):
            continue
        bad.append((r["name"], fix))
    return bad


def report(bad, store):
    lines = ["[output-rules] this message breaks an output rule. Fix it before you finish:"]
    for name, fix in bad:
        lines.append(f"    {name} -> {fix}")
    lines += [
        "  When you put the same symbol at two different points in time, say which is",
        "  measured and which is predicted.",
        "  If you are told the same thing twice, do not add a paragraph of prose:",
        f"  add one line to {store}",
        "  (mechanism: hooks/output_rules_guard.py)",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True, description=__doc__.split("\n")[0])
    ap.add_argument("--rules", help="rule table to use instead of the default")
    ap.add_argument("--transcript",
                    help="judge this JSONL transcript instead of reading hook "
                         "JSON on stdin (writes no log line)")
    args = ap.parse_args(argv)

    store = pathlib.Path(args.rules) if args.rules else rules_path()
    dry = bool(args.transcript)

    transcript = args.transcript
    if not dry:
        try:
            data = json.load(sys.stdin)
        except Exception:
            return 0
        if data.get("stop_hook_active"):
            return 0            # we already blocked once; do not loop
        transcript = data.get("transcript_path") or ""

    rules, err = load_rules(store)
    if err:
        print(f"[output-rules] the rule table is unusable, so no rule is being "
              f"checked until it is fixed.\n"
              f"  {err}\n"
              f"  location: {store}",
              file=sys.stderr)
        return 2

    texts = assistant_texts(transcript or "")
    if not texts:
        return 0                # transcript-side accident: do not block
    bad = judge(texts, rules)
    if not bad:
        return 0
    if not dry:
        log_fires([n for n, _ in bad], log_path())
    print(report(bad, store), file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
