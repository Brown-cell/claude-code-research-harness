# claude-code-research-harness

[![tests](https://github.com/Brown-cell/claude-code-research-harness/actions/workflows/tests.yml/badge.svg)](https://github.com/Brown-cell/claude-code-research-harness/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Hooks and conventions for [Claude Code](https://docs.anthropic.com/en/docs/claude-code),
for people who use it every day on the same project for months.

You tell Claude Code something. It agrees. Four days later it does the same
thing again, and the instruction was in CLAUDE.md the whole time.

This repository is what I built after that happened enough times: six hooks
and two conventions, all plain Python and Markdown, no dependencies, that
make rules, memory and context handoffs hold over a year of daily use on the
same body of work. I am a chemistry undergraduate at the University of Tokyo
and none of this is about chemistry.

Here is the Stop hook refusing to end a turn, on the fixture that ships in
`tests/`:

```
$ python hooks/output_rules_guard.py --rules rules/output_rules.example.json \
        --transcript tests/fixtures/example_transcript.jsonl
[output-rules] this message breaks an output rule. Fix it before you finish:
    p95 -> write it as "p95 (= the 95th percentile: 1 request in 20 is slower than this)" the first time it appears
    minimising words -> Drop the word. 'Simply run the migration' tells the reader their difficulty is their own fault, and it hides the work: if it really is one command, the command alone says so. Write the command.
    saying it works without running it -> If you have not executed it, say so in the same sentence: 'unverified, I have not run this on Windows'. Mixing what you ran with what you expect is the one failure mode that makes the whole report unusable, because the reader can no longer tell which half to trust.
  If you are told the same thing twice, do not add a paragraph of prose:
  add one line to rules/output_rules.example.json
  (mechanism: hooks/output_rules_guard.py)
$ echo $?
2
```

## Three things in here you may not have seen elsewhere

**A rule must state what it lets through.** Every `forbid` and `require` rule
in the table carries a `negative`: one or more sentences that must not fire.
The hook checks them when it loads the table and refuses to run if one does.
A check that runs on every message with a net that is too wide does not fail
visibly, it interrupts unrelated work every day until you switch the whole
thing off. When a real false positive shows up, you paste the sentence into
`negative`, narrow the pattern until the table loads again, and that false
positive can never come back. One of the shipped rules carries a sentence
caught this way while writing this repository (a cloud region label that
looked exactly like an internal check id).

**The preflight injects only the rules you broke this week, and empties
itself.** The Stop hook detects but does not deter: by the time it fires the
message is written. Over one six-day stretch my top five rules fired 30, 27,
25, 25 and 14 times, on six days out of six. So a UserPromptSubmit hook reads
the guard's fire log and puts the rules that fired on two or more distinct
days in the last seven in front of the turn. A rule you have stopped breaking
drops off after seven quiet days without anyone pruning it. The whole table is
never injected, because the table only grows.

**A hook that fires when you write a rule as prose.** When a Write or Edit
lands in a document whose job is to change future behaviour (CLAUDE.md, a
protocol, a checklist), `prose_rule_guard.py` prints one question and never
blocks: can this be checked by a machine? If yes, build the check and leave a
one-line pointer. If no, keep the prose and say in your reply that it is
unenforced. It exists because one rule in my setup was written into the same
guardrails document three times and broken all three times. The count that
settled the design: across a few hundred sessions, nearly every instruction I
had to repeat was already written down somewhere that gets injected every
session. The only repetitions that stopped were the ones converted into a
check the same day.

The other three mechanisms are below. The reasoning behind all of them,
including the numbers, is in [`docs/why.md`](docs/why.md).

## The rest

### Memory: one fact per file, and an index with a budget

`memory/` + `hooks/memory_lint.py` (SessionStart)

The file layout is Claude Code's own auto-memory convention: one durable fact
per Markdown file, four prefixes (`user_`, `feedback_`, `project_`,
`reference_`), and a `MEMORY.md` of one-line pointers that is injected into
every session. What this repository adds is a budget on the index (110 lines,
18000 bytes, because every line of it is paid for on every turn and past a
certain size the index gets skimmed instead of read), an archive file for
finished work, and a lint that runs at session start and says nothing when
the directory is clean. The lint flags dead links, orphan files, an oversized
index, expired dates, drift (a file changed after the index line describing
it) and dormancy. It reports and stops; a human decides. Silencing one line
costs one word, `lint-ok` on that line. Details in
[`memory/README.md`](memory/README.md).

### Context handoff: two lines, and a list instead of a guess

`hooks/handoff_stop.py` (Stop) + `hooks/handoff_sessionstart.py` (SessionStart)

Every turn re-reads the whole window in cache, so the cost of a session grows
with the square of its length. At 300k tokens of context, restarting from a
handoff note pays for itself in under three turns. The Stop hook asks for a
handoff at two thresholds: a soft line at 90k, where you are asked only if the
work is at a natural seam, and a hard line at 150k, where you are asked
regardless. One line cannot do both jobs; an early one gets ignored mid-task
and a late one arrives after the expensive turns are paid for. Both are
overridable with `HANDOFF_SOFT` and `HANDOFF_HARD`.

The SessionStart side used to print one pointer, the most recently modified
handoff. Across 259 such hints in my transcripts, 41% were followed and 16%
were ignored in favour of a different handoff, so the pointer was guessing the
wrong track one time in six. Now there is one living file per track,
`handoff/NOW-<track>.md`, overwritten in place, and the hook prints the list.

### Delegation: a ten-heading spec, and the hook that checks it

`agents/` + `docs/delegation_protocol.md` + `hooks/spec_gate.py` (PreToolUse)

Four subagent roles with input and reporting contracts: `build`, `exec`,
`sweep` (read-only, returns text) and `premortem` (watches a worker, fires at
most once). The protocol document is where the window economics are worked
out. In one measured week 51% of my spend was cache reads, and the parent
window had paid 149M tokens of re-reads on under 4M tokens of new material.
Fan-out multiplies that: 64 subagents given 120KB each was 4.4M tokens in one
afternoon.

The spec template has ten fixed headings. I pulled 122 delegation prompts out
of my own transcripts and found six roles being written under 49 different
heading names; the one role that had a single consistent name was the one I
had added as a named field. The three headings the old template lacked
(`Discretion`, `Prohibited`, `Failure mode`) were the three that never
appeared at all. A field with a name travels to the next job. Prose does not.

`spec_gate.py` is the check: a PreToolUse hook on the Agent tool that blocks a
delegation whose prompt is missing a heading, has them out of order, or leaves
one blank. It is the newest file here and the one the `prose_rule_guard`
would have asked for, since the rest of that section was prose until it was
written.

## Next to the others

The larger repositories that attack the same "I told it once" problem do it by
remembering the correction. [pro-workflow](https://github.com/rohitg00/pro-workflow)
turns each one into a rule in SQLite and loads the rules at session start;
[Continuous-Claude-v3](https://github.com/parcadei/Continuous-Claude-v3) has a
daemon extract learnings into PostgreSQL. Claude Code's own auto-memory is the
same route with Markdown files. All three end with the model reading a note
and deciding to follow it, which is the step that failed in the first place.
Here a correction becomes a regular expression, and the check runs on the
finished message and exits 2. The model is not consulted. The turn does not
end until the sentence is fixed.

| | a correction is stored as | what stops the repeat | to run it |
| --- | --- | --- | --- |
| this repository | a regex in a JSON table, with sentences it must let through | Stop hook, exit 2 | Python |
| pro-workflow | a rule in SQLite (FTS5), loaded at session start | the model reading the rule | Node, an npm build, SQLite |
| Continuous-Claude-v3 | a learning in PostgreSQL + pgvector, extracted by a daemon | the model recalling it | Docker, PostgreSQL, uv |
| Claude Code auto-memory | a line in a Markdown file, `MEMORY.md` injected each session | the model reading the note | nothing, it is built in |

None of them, as far as I have read, asks a rule to state what it must not
catch. That is the first of the three ideas above, and the one I would keep
if I had to drop the rest.

[cc-safety-net](https://github.com/kenryu42/cc-safety-net) and
[claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery)
sit at a different layer: they block tool calls (`rm -rf`, reads of `.env`)
before they run. Nothing here does that, and nothing here conflicts with
them. `spec_gate.py` is the only PreToolUse hook in this repository and it
looks at one tool, the Agent call.

## Install

1. Copy `hooks/` and `rules/` into your project.
2. `cp rules/output_rules.example.json rules/output_rules.json`, then delete
   every rule that is not about a mistake you actually make. Two real rules
   beat twelve aspirational ones.
3. Merge the `hooks` block of [`settings.example.json`](settings.example.json)
   into your `.claude/settings.json`. `$CLAUDE_PROJECT_DIR` is expanded by
   Claude Code; replace `python` with a full interpreter path if needed.
4. Optional: copy `agents/*.md` into `~/.claude/agents/` or `.claude/agents/`.
5. Start a session. If your memory directory is somewhere unusual, set
   `HARNESS_MEMORY_DIR`; otherwise the lint looks in
   `~/.claude/projects/<slug>/memory`.

Make the guard fire on purpose with the command at the top of this page. Exit
code 2 means it is live. That flag pair takes the same code path as the hook
and writes no log line, so you can ask the guard about any transcript for
free.

| Variable | Effect |
| --- | --- |
| `HARNESS_RULES_FILE` | rule table (default `$CLAUDE_PROJECT_DIR/rules/output_rules.json`) |
| `HARNESS_RULES_OPTIONAL=1` | a missing rule table passes instead of stopping the turn |
| `HARNESS_GUARD_LOG` | where rule firings are logged (default `$CLAUDE_PROJECT_DIR/logs/`) |
| `HARNESS_MEMORY_DIR` | memory directory, if the guess is wrong |
| `HARNESS_HANDOFF_DIR` | handoff notes (default `$CLAUDE_PROJECT_DIR/handoff`) |
| `HANDOFF_SOFT` / `HANDOFF_HARD` | context thresholds in tokens |

## Writing a rule

A `define` rule is two fields:

```json
{ "name": "p95", "kind": "define", "pattern": "\\bp95\\b",
  "gloss": "the 95th percentile: 1 request in 20 is slower than this" }
```

A `forbid` or `require` rule also needs the `negative`:

```json
{ "name": "saying it works without running it", "kind": "require",
  "pattern": "\\bshould work\\b",
  "requires": "unverified|untested|have not run",
  "message": "if you did not execute it, label it unverified in the same sentence",
  "negative": ["I ran the suite: 41 passed, 0 failed.",
               "This should work on Windows. Unverified, I only ran it on Linux."] }
```

The table never fails silent. A missing file, a syntax error, a broken regular
expression or a `forbid` rule without a `negative` all stop the turn with a
message saying which line, because an empty rule list and a misplaced comma
used to look identical from the outside.

The example table ends with a `_not_convertible` entry: a rule I tried to
mechanise, could not, and left as prose with the reason written next to it.
A rule that never fires is worse than an admitted gap, because it looks like
the problem is handled.

## Running this as a one-hour session

I have used this order with other students. Each step is a failure the room
has already had.

1. Ask who has told Claude the same thing more than twice. Show
   `prose_rule_guard.py`, 100 lines, and the question it asks. (10 min)
2. Write one rule together for a habit the room recognises ("simply",
   "should work"). Run the guard on a fake transcript and watch it exit 2.
   (15 min)
3. Write a rule whose net is too wide, watch the table refuse to load, narrow
   it. This is the one idea that generalises past this repository. (10 min)
4. Draw the cost of a turn against context size, then the two handoff lines.
   Ask how many people have had a long thread auto-compacted. (10 min)
5. Memory: one fact per file, an index with a budget, a lint that detects and
   does not correct. (10 min)
6. Delegation: raw material goes in neither the parent nor the child window,
   and the report separates verified from guessed. (5 min)

Homework is one rule in their own table, that night. Anyone who ships a second
rule in the following week has understood the whole thing.

## Caveats

- The numbers (7-day window, 90k/150k, 45-day dormancy, a 110-line index)
  came from measuring my own sessions. They are starting points. Measure yours.
- The guard reads only the final assistant message of a turn, and only the
  last 4MB of the transcript. An old gloss can fall out of the window; the
  cost is being asked to define a term once more.
- The regular expressions are English-shaped. The machinery does not care
  what language the patterns are in.
- Hooks run on every turn. Keep them fast, and keep them quiet when there is
  nothing to say.
- The guard reads Claude Code's transcript format and nothing else. Codex,
  Cursor and the other CLIs are not supported, and I have not tried.
- Tested on Windows with CPython 3.12 and on Ubuntu in CI with 3.11 and 3.12.
  No third-party dependencies. `pytest tests/` is the check.

## License

MIT. See [LICENSE](LICENSE).
