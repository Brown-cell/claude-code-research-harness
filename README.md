# claude-code-research-harness

Five small mechanisms that make a long-running Claude Code setup keep its own
rules: an output-rule checker, a memory convention with a lint, a two-tier
context handoff, tiered delegation to subagents, and a hook that asks whether
the rule you are writing as prose could be a machine check instead.

Everything here is plain Python and Markdown. There is nothing to install
beyond copying the files and wiring six lines into your `settings.json`.

## What this is

If you use Claude Code for more than a few weeks on the same body of work, you
will notice the same three failures:

1. **You tell it something, it agrees, and a week later it does the same thing
   again.** The instruction is written down. Being written down changes nothing.
2. **The context window fills up.** Every turn re-reads the whole window, so the
   last third of a long session costs several times what the first third did,
   and the thread eventually gets compacted into something worse than a note you
   would have written yourself.
3. **What it knows about your work lives in your scrollback.** Clear the thread
   and it is gone, so you re-explain the same background at the start of every
   session.

This repository is the set of answers that survived. It is deliberately not a
framework: each piece is one file, does one thing, and can be deleted on its own
without touching the rest.

## Who made it and why

I am a chemistry undergraduate at the University of Tokyo. I run the
computational and paperwork side of a research group's work through Claude Code
-- planning, analysis, scripts, reports, scheduling, the correspondence that
comes with all of it -- and I have been doing it daily for about a year. None of
these mechanisms were designed up front. Each one exists because a specific
thing went wrong twice, and the second time it was cheaper to build a check than
to write another paragraph asking myself to be careful. The origin of each one
is written into the docstring of its file, because the reason a rule exists is
worth more than the rule.

Nothing about chemistry is in here. The mechanisms turned out to be about
working with an agent over months, which is the same problem whatever you study.

## The five mechanisms

### 1. Output rules -- a table, not a document

`hooks/output_rules_guard.py` (Stop) + `rules/output_rules.json`

A rule table with three kinds of check: `define` (gloss this term the first time
it appears), `forbid` (do not use this phrase), `require` (if you write this,
you must also write that). The Stop hook checks the final message and refuses to
end the turn on a violation.

The important design choice is that the rules are **data in a separate file**,
not conditions in the code. When you catch yourself being told the same thing
twice, converting it into a check has to be a one-minute job or you will not do
it -- and in practice the prose version does not hold. A rule needs a home you
can edit while the annoyance is fresh.

```
   your message  ->  [Stop hook]  ->  rules/output_rules.json
                          |               define / forbid / require
                          |
                    violation? -> exit 2, message says how to fix it
                    clean?     -> turn ends
```

Two properties are worth copying even if you write your own version. **It never
fails silent**: a missing table, a syntax error or a broken regular expression
stops the turn, because an empty rule list and a misplaced comma used to look
identical. And **every `forbid`/`require` rule must carry a `negative`** -- an
example sentence that must not fire, which the hook verifies at load time. A
check that runs on every message is a landmine if its net is too wide, and this
makes the width of the net something you have to state.

### 2. Preflight -- the rules you actually broke this week

`hooks/output_rules_preflight.py` (UserPromptSubmit)

A Stop hook detects but does not deter: by the time it fires, the message has
been written and you have read it. Over one six-day stretch the top five rules
in my table fired 30, 27, 25, 25 and 14 times -- on six days out of six. Another
rule would have stopped in the same place.

So this hook reads the guard's fire log and injects, before the turn starts, the
short list of rules **you actually broke in the last seven days**. Not the whole
table -- the table only grows, and injecting all of it taxes every turn. A rule
that stops firing drops off the list by itself, so it stays short without anyone
pruning it.

### 3. Memory -- one fact per file, with an index that has a budget

`memory/` + `hooks/memory_lint.py` (SessionStart)

The convention: one durable fact per file, four prefixes (`user_`, `feedback_`,
`project_`, `reference_`), and a single `MEMORY.md` index of one-line pointers
that gets injected into every session. The index is the thing with a size
budget; the files behind it can be as long as they need to be. Details and the
worked example are in [`memory/README.md`](memory/README.md).

The lint is a detective, not a corrector. It flags dead links, orphan files, an
oversized index, expired dates, drift (a file that changed after the index line
describing it), and dormancy. It prints nothing when the index is clean, which
is what makes it tolerable on every session start. What it cannot do -- spot
that two files contradict each other -- is exactly what the periodic
read-it-all review is for, and the last thing it prints is the reminder.

### 4. Context handoff -- two lines, not one

`hooks/handoff_stop.py` (Stop) + `hooks/handoff_sessionstart.py` (SessionStart)

One turn at context C costs roughly `0.1 * C` in cache reads before any work
happens, and context grows monotonically, so an *n*-turn window costs about
*n²*. Restarting costs one session baseline plus writing the handoff. At 300k
that pays for itself in under three turns.

Hence two thresholds. At the **soft line** (90k) you are asked for a handoff
*only if the work is at a natural seam*; at the **hard line** (150k) you are
asked unconditionally. One line cannot do both jobs: an early one gets ignored
mid-task, a late one arrives after the expensive turns are paid for. Both are
overridable with `HANDOFF_SOFT` / `HANDOFF_HARD`.

```
   0 ......... 90k ................. 150k ................>
               soft: hand off        hard: hand off now,
               if at a seam          even mid-task
```

The SessionStart side prints the list of live tracks. It used to print one
pointer -- the newest handoff -- and across several hundred transcripts only 41%
of those hints were followed, while 16% were ignored in favour of a *different*
handoff, meaning the pointer had guessed the wrong track. Running several
threads at once is normal, so modification time can never key this correctly.
The fix was to stop guessing: one living file per track, `handoff/NOW-<track>.md`
overwritten in place, and print the list.

### 5. Tiered delegation -- and the hook that keeps rules from being prose

`agents/` + `docs/delegation_protocol.md` + `hooks/prose_rule_guard.py` (PostToolUse)

Four subagent roles with explicit input and reporting contracts: `build` (writes
code from a settled spec), `exec` (mechanical execution), `sweep` (read-only
extraction, returns text and writes nothing) and `premortem` (watches a worker
and fires at most once). The economics are in
[`docs/delegation_protocol.md`](docs/delegation_protocol.md); the short version
is that raw material must not land in the parent window **or** in the child
windows, and the reporting contract must separate what was verified from what
was guessed.

The last hook is the smallest and the one I would keep if I could keep only one.
When you write into a document whose job is to change future behaviour, it fires
once and asks: *can this be checked by a machine?* It never blocks. It just
refuses to let "I wrote it down" pass unexamined, because writing it down is the
weakest enforcement there is -- one rule in my setup was written into the same
document three times and broken anyway.

## Install

Five minutes.

1. Copy `hooks/` and `rules/` into your project (any layout; the paths below
   assume the repository root is your project root).
2. `cp rules/output_rules.example.json rules/output_rules.json`, then delete
   every rule that is not about a mistake you actually make. Two real rules beat
   twelve aspirational ones.
3. Merge the `hooks` block of [`settings.example.json`](settings.example.json)
   into your `.claude/settings.json`. Replace `python` with the interpreter you
   want if it is not on your `PATH`; `$CLAUDE_PROJECT_DIR` is expanded by Claude
   Code and is how every path here stays relative.
4. Optional: copy `agents/*.md` into `~/.claude/agents/` (available everywhere)
   or `.claude/agents/` (this project only).
5. Start a session. If your memory directory is somewhere unusual, set
   `HARNESS_MEMORY_DIR`; otherwise the lint guesses
   `~/.claude/projects/<slug>/memory`, where `<slug>` is your project path with
   every character outside `[A-Za-z0-9]` replaced by `-`.

Check it works by making the guard fire on purpose:

```
python hooks/output_rules_guard.py --rules rules/output_rules.json \
       --transcript tests/fixtures/example_transcript.jsonl
```

Exit code 2 and an English message means it is live. That flag pair is also the
general inspection entry point: it takes the same code path as the hook and
writes no log line, so you can ask the guard what it would say about a message
instead of guessing.

Environment variables, all optional:

| Variable | Effect |
| --- | --- |
| `HARNESS_RULES_FILE` | rule table location (default `$CLAUDE_PROJECT_DIR/rules/output_rules.json`) |
| `HARNESS_RULES_OPTIONAL=1` | a missing rule table passes instead of stopping the turn |
| `HARNESS_GUARD_LOG` | where rule firings are logged (default `$CLAUDE_PROJECT_DIR/logs/`) |
| `HARNESS_MEMORY_DIR` | memory directory, if the guess is wrong |
| `HARNESS_MEMORY_ACTIVE_SECTIONS` | index sections where dormancy is worth flagging |
| `HARNESS_HANDOFF_DIR` | handoff notes (default `$CLAUDE_PROJECT_DIR/handoff`) |
| `HANDOFF_SOFT` / `HANDOFF_HARD` | context thresholds in tokens |

## Growing your own rules

The table is meant to be added to, one line at a time, at the moment something
annoys you. A `define` rule is two fields:

```json
{ "name": "p95", "kind": "define", "pattern": "\\bp95\\b",
  "gloss": "the 95th percentile: 1 request in 20 is slower than this" }
```

A `forbid` or `require` rule needs one more thing, and this is the part worth
understanding:

```json
{ "name": "saying it works without running it", "kind": "require",
  "pattern": "\\bshould work\\b",
  "requires": "unverified|untested|have not run",
  "message": "if you did not execute it, label it unverified in the same sentence",
  "negative": ["I ran the suite: 41 passed, 0 failed.",
               "This should work on Windows -- unverified, I only ran it on Linux."] }
```

`negative` is a list of sentences that **must not** fire, and the hook checks
them every time it loads. It exists because a rule that runs on every message is
different from a test: if its net is too wide it will interrupt unrelated work
every day, and you will end up turning the whole thing off. Stating what should
escape the net is how you keep that from happening quietly.

The workflow, once a false positive shows up in real use: paste the exact
sentence into `negative`, then narrow `pattern` until the table loads again. The
false positive can now never come back, and the table carries a record of what
it learned. One of the shipped rules has such a sentence in it, from a false
positive caught while writing this repository.

## Teaching with this

An hour, in this order. It works because each step is a failure the room has
already had.

1. **(10 min) The prose problem.** Ask who has told Claude the same thing more
   than twice. Everyone has. Show `prose_rule_guard.py` -- 100 lines, and the
   question it asks. Nobody argues with the premise once it is named.
2. **(15 min) Write one rule together.** Pick a habit the room recognises
   ("simply", "should work"), write the JSON, run the guard on a fake transcript,
   watch it exit 2. This is the moment where it becomes concrete: they have
   converted a complaint into a check, in front of everyone, in two minutes.
3. **(10 min) The negative.** Deliberately write a rule with a net that is too
   wide, watch the hook refuse to load it, then narrow it. This teaches the one
   idea that generalises past this repository: an always-on check must state
   what it lets through.
4. **(10 min) The window.** Draw the `0.1 * C` per turn, show that *n* turns cost
   *n²*, and show the two lines. Ask how many people have had a long thread
   auto-compacted. Then show the track list.
5. **(10 min) Memory.** One fact per file; an index with a budget; the lint that
   is a detective and not a corrector. Point out what it deliberately cannot do.
6. **(5 min) Delegation.** The two window rules -- raw material in neither the
   parent nor the child -- and the reporting contract that separates verified
   from guessed.

Leave them with the smallest possible homework: **one rule, in their own table,
tonight.** Anyone who ships a second rule in the following week has understood
the whole thing.

## Caveats

- **This is one person's setup, generalised.** The numbers in it (7-day window,
  90k/150k, 45-day dormancy, a 110-line index budget) came from measuring my own
  sessions. They are starting points, not findings. Measure your own.
- **Not everything can be a rule.** `rules/output_rules.example.json` ends with a
  `_not_convertible` entry: something I tried to mechanise, failed, and left as
  prose with the reason recorded. A rule that never fires is worse than no rule,
  because it looks like the problem is handled.
- **The guard reads only the final assistant message** of a turn, and only the
  tail of the transcript. Long conversations lose the earliest glosses; the
  failure mode is being asked to define a term once more, which is harmless.
- **The regular expressions are English-shaped.** If you work in another
  language, the patterns are yours to write; the machinery does not care.
- **Hooks run on every turn.** Keep them fast and keep them quiet when there is
  nothing to say. A hook that talks when everything is fine gets ignored, and
  then it may as well not exist.
- **Tested on Windows with CPython 3.12**, no third-party dependencies. Other
  versions and platforms are unverified -- the code is plain standard library,
  and `pytest tests/` is the check if you want to know for sure.

## License

MIT. See [LICENSE](LICENSE).
