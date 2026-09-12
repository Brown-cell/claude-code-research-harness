# Memory conventions

What Claude Code knows about your work between sessions lives in a directory of
Markdown files, and one index file out of that directory is injected into every
session. That injection is the whole design constraint: **the index is paid for
on every single turn, and the files behind it are paid for only when read.**

Everything below follows from that.

## One fact per file

A memory file holds one durable fact and its consequences. Not one project, not
one topic -- one fact. "The user does not want X" is a file. "How the build
pipeline is wired" is a file. When two facts share a file, one of them gets
found and the other one does not, because whoever searches is searching for the
first.

The test for whether something belongs in memory at all: **will this still be
true, and still matter, in three months?** A decision that was made once is
memory. What you are doing today is a handoff note, not memory.

## Four prefixes

The prefix is the first thing you see in a listing, so it should say what kind
of thing the file is:

| Prefix | Holds | Example |
| --- | --- | --- |
| `user_` | who the person is, their situation, their constraints | `user_background.md` |
| `feedback_` | a correction they gave that must not need giving again | `feedback_no_unverified_claims.md` |
| `project_` | live work: state, decisions, open questions | `project_thesis_pipeline.md` |
| `reference_` | how something is set up and how to use it | `reference_cluster_access.md` |

`feedback_` is the one that matters most and the one people skip. Every time a
correction is given, it either becomes a file or it will be given again.

## The index has a budget

`MEMORY.md` is a list of one-line pointers, grouped under a few headings. Each
line is a link plus the shortest possible hook -- **enough to know whether to
open the file, and not one word more.**

The budget in the lint is **110 lines / 18000 bytes**. It is not a style
preference. Past that, the injection starts costing real money on every turn,
and -- worse -- the index starts being skimmed instead of read, at which point a
longer index conveys *less* than a shorter one.

Two rules keep it inside the budget:

- **The index holds names, not contents.** Dates, numbers and reasoning live in
  the file. If a number is in the index, it will go stale there, and nobody will
  notice because nobody diffs an index against its files.
- **Finished work moves to `MEMORY_ARCHIVE.md`.** The archive has no budget. Its
  job is that a completed project stays findable without occupying a line of the
  live index. Archived is not deleted; it is one hop further away.

## `lint-ok`

`hooks/memory_lint.py` runs at session start and flags dead links, orphan files,
expired dates, drift and dormancy. It is a **detective, not a corrector**: it
prints what looks wrong and stops. A human or a session decides.

To silence a line it gets wrong, put the string `lint-ok` anywhere on that line
of the index. That is deliberately the crudest possible escape hatch. An escape
hatch that costs one word gets used; one that costs a configuration file does
not, and then the whole lint gets switched off instead.

Use it for real exceptions, and say why:

```markdown
- [Separations background](reference_separations.md) -- keep even though dormant;
  the technique is planned for next year (lint-ok)
```

A dormancy flag is a question, not a verdict. Some of the most valuable files
are the ones nothing has touched in months.

## The review the lint cannot do

Two files that contradict each other, or a durable fact buried inside a file
about something else, cannot be found by pattern matching. Every few weeks, read
the whole directory as if you had never seen it, and ask of each file: is this
still true, is it findable, does it contradict anything. Write the date into
`.last_full_review` when you are done -- the lint's final reminder is keyed off
that file, and it is the only bucket that is about your attention rather than
the directory's contents.

## Files here

- [`MEMORY.example.md`](MEMORY.example.md) -- what an index looks like.
- [`example_feedback.md`](example_feedback.md) -- what one file looks like,
  including the front matter and the two sections that make a correction usable
  by a future session.
