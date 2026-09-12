# Delegation protocol

How to hand work to a subagent without paying more than you save. This is a
condensed English version of a longer internal document; the parts kept here are
the ones that generalise.

## 0. The objective function

There are two goals and they are not the same goal:

- **Constraint**: quality must not drop below what the top-level window would
  have produced alone.
- **Objective**: subject to that, minimise what the top-level window spends.

Total spend across all windows is *not* the objective. If 50k in one window and
"30k parent + 30k child" produce the same quality, the second one wins. The
parent's window is the scarce resource; the children's are cheap.

The parent's comparative advantage is deep search, resolving ambiguity, and not
asserting things that are false. Only work where that advantage does nothing
should go down.

## 1. The three-question test

Delegate only if all three are yes.

1. **Can you write the spec?** If you have to make judgement calls while
   writing it, the work is not delegable. Being unable to write the spec is the
   signal, not an obstacle to route around.
2. **Would you catch a mistake at review?** A mechanical check (compile, test,
   run, diff) or a quantitative comparison means yes. "Detecting a plausible
   lie would take expert judgement" means no.
3. **Is it worth the round trip?** Ten minutes and three edits of your own work
   costs less than a spec and a review.

Default: do it yourself. Delegation is an optimisation you apply when you are
confident, not a duty.

## 2. Window economics

This is the part most people miss, and it is measurable. In one week of my own
usage, **51% of all spend was cache reads**, re-reading context that had
already been read. The parent window had taken in under 4M tokens of new
material and paid for 149M in cache reads: roughly **39 re-reads per token**.

Two consequences:

- **A turn costs about `0.1 x current context` before any work happens.** Merely
  having a large window is charged on every turn.
- **Context grows monotonically, so an *n*-turn window costs about *n²*.**
  Splitting the same work into two half-length windows nearly halves the
  carrying cost.

### Rule 1: do not put raw material in the parent window

Multi-file reads, whole logs, first passes over documents and images go to a
read-only subagent that returns a summary. A token the parent reads is charged
again on every turn until that window dies.

### Rule 1b: do not put it in the child windows either. Fan-out is a multiplier

I learned this by hitting a monthly ceiling. Reading rule 1 as being about the
parent only, I gave **64 subagents about 120KB of material each and had each use
one chapter of it**: 4.42M tokens. **Cost = input size x turns x agents.** Images
were not the problem; 120KB x 19 turns x 64 agents was.

What follows from it:

- **Do not send them looking. Cut out the fragment they need and hand it over.**
  Cutting is deterministic code and therefore free.
- **Do not have both a structured return value and a file output.** The body
  goes in the file; the return value is a summary and a count.
- **Put a tool budget in the prompt.** "Open one image, write one file, open
  nothing else." Turn count matters as much as input size, and unstated it
  expands on its own, one run reached 72 turns.
- **Make it idempotent to resume before you fire.** You cannot avoid limits;
  you can make hitting one cost nothing.

### Rule 2: decide the window's lifespan before you start

Cross the hard line and write a handoff even mid-task. See
[`why.md`](why.md) for where the two thresholds come from.

### Rule 3: give windows jobs

| Work | Window |
| --- | --- |
| Judgement, adjudication, planning, priorities, design decisions, final synthesis, the report to the user | top-level |
| Implementation, refactoring, debugging | implementer subagent |
| Routine execution, data processing, cataloguing | executor subagent |
| Iterating on figures; first pass over images or documents | a subagent (the loop is long and the material is heavy) |
| Read many files, extract, cross-check | read-only subagent |

If a judgement task turns out to need implementation, write the spec in the
judgement window and send it down, do not move windows. If an implementation
window turns out to need a design decision, stop there and take it back up.

### Rule 4: subagents catch the same disease

Measured average context of my own subagents: 130-140k. Write the reading scope
into the spec. Do not let them read whole things.

### Rule 5: an unspent budget is also a failure

The point is pacing, not austerity. If there is room, use it.

## 3. The unit of control is the engine, not the harness

Worth knowing before you swap tools. Hooks belong to the engine that runs the
tool calls, not to the interface you type into. In a controlled test, same
neutral harness, same script, only the engine swapped, the run that went
through the Claude Code engine had its shell command recorded by the
PreToolUse hook and blocked by a guard, and the run on another provider used
the harness's own built-in shell tool and left no trace in the hook log at all.

So: **switching the interface keeps your guardrails; switching the engine
removes them, silently.** Any rule that depends on a hook has to be restated as
a prohibition the moment the engine changes.

## 4. The spec template: ten headings, fixed strings

Use these ten headings, in this order, with these exact names, for any
delegation that writes something.

```
# Read first        what to read on top of the defaults; "defaults" if nothing
# Background        why this is being done (shared brief; identical across parallel streams)
# Task              what, and how far
# Discretion        where the receiver may decide. "none" if you specified everything
# Acceptance        the check command and the expected result
# Write paths       writing outside this list is forbidden; say new vs overwrite
# Prohibited        what not to do beyond writing (do not commit, do not run, ...)
# Tool budget       what may be opened, how many writes, how many turns
# Failure mode      what survives a crash; what to do if the premise turns out wrong
# Reporting         defaults to the agent definition's contract; write it only to add
```

**No blank fields.** A heading with nothing to say gets one of four reserved
words: `any` (receiver's choice), `defaults` (as in the agent definition),
`none` (not part of this delegation), `-` (not applicable). A blank cannot be
told apart from an omission. `hooks/spec_gate.py` checks all of this on every
Agent call before the prompt is sent; a spec that fails it never leaves the
parent window.

### Why fix the strings and not just the roles

I pulled 122 real delegation prompts out of my own transcripts and counted. Six
roles were being expressed with **49 different heading names**: the "background"
role alone appeared under 14 different words. Exactly one role was written with
a single consistent name, "tool budget", and that was the one I had added
*as a named field* after the fan-out accident above.

The other lesson from that same accident, "write so a crash leaves something
behind", I recorded as prose. It appeared in four prompts on one project and
never travelled to another.

**Only a field with a name travels to the next job.** That is the whole reason
the strings are fixed. And once the vocabulary is closed, a machine can check it.

Measured against those 122 prompts, the three headings never used even once were
`Discretion`, `Prohibited` and `Failure mode`, precisely the three the old
template did not have. The prompts that followed the old template followed it
fine. What was missing was fields, not discipline.

### On `Discretion`

The old instruction, "leave no room for judgement", cannot be followed: you
cannot write everything down. What goes unwritten becomes a blank, and the
receiver cannot tell a blank from a deliberate omission. So instead of removing
the room for judgement, **name where it is**: what they may choose, what they
must not move, and which way to lean when unsure.

### On `Failure mode`

The worst way for delegated work to end is: it was on the plan, it dragged, and
at the last minute the answer is "I could not do it". Two things are lost: the
chance to propose a fix, and all the time spent hesitating. The parent cannot
intervene midway, so the only way to recover the first is to **land partial
results early**. Write three things:

1. **What survives a crash**: "write section by section, never all at once".
2. **When to come back empty-handed**: if the premise is wrong, return it
   unfixed. "The job is not done until it passes" reads as *keep pushing*; this
   is where you bound the pushing.
3. **The give-up point**: how many attempts, how many minutes.

## 5. Review, and escalation

- **The parent reviews, personally.** Read the report, re-run the acceptance
  check (or confirm the evidence of the run), read the diff. An independent
  verifier is an addition to that, never a replacement.
- **Failure means**: the acceptance criteria were not met, or the contract was
  broken, an unverified assertion, a write outside the allowed paths, or the
  acceptance criteria quietly relaxed.
- On failure: improve the spec and re-delegate to the same tier **once**. Then
  move up a tier. Then take it back yourself. If you are stuck too, get an
  independent diagnosis from a different model, do not hit the same wall with
  the same head three times.
- **Keep partial results.** Never throw away work because the run failed.
- **When three or more workers run at once, stand up one verifier** whose only
  job is to check that the things they said they would write actually exist.
  Across two measured weeks, the share of runs that ended without producing the
  artefact they promised went from 15% to 39%, and the failure was not bad
  output, it was *no* output. Reviewing quality does not catch that; checking
  existence does.

## 6. Running several streams at once

- The top-level window **coordinates and does not do object-level work**.
- **Write ownership is disjoint** between streams, stated in each spec. Streams
  do not talk to each other; everything goes through the parent.
- **Pass the brief down verbatim. Do not summarise it.** A stream that
  re-delegates is the second link in a chain of retelling, and that is exactly
  where a task comes back facing the wrong direction. Only the parent may
  shorten a brief.
- **When you send the same spec to several workers, change exactly one
  variable.** Freeze the wording, the headings and the order; vary only the
  assignment.
- When they are all done, the parent checks for contradictions between them --
  terminology, paths, conclusions, before synthesising.
