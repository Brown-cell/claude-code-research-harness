# Why any of this is shaped the way it is

Every mechanism in this repository is an answer to something that went wrong
twice. The rules themselves are cheap to copy; the reasoning is the part that
tells you when to break them, so it is written down here rather than left in the
commit history.

## A rule written as prose is not enforced, and after a while it is not even read

The evidence that settled this was not an argument, it was a count. I scanned a
few hundred sessions for places where the same instruction had to be given
again, and found that in nearly every case **the instruction was already written
down**, in a document that gets injected into every session. One had been
recorded two minutes after it was given and was broken again four days later.
The only cases where the repetition actually stopped were the ones where, that
same day, the prose was converted into a machine check.

A separate case makes the same point from the other direction. A rule about file
encoding was written into an operational guardrails document three times, in
three different sections, and was violated all three times, once loudly (a
scheduled task died at once) and once silently (a script exited zero and did
nothing, and a file quietly lost eleven lines). Three paragraphs, zero
enforcement.

So the working rule became: **the second time the same kind of mistake happens,
build a mechanism instead of writing another paragraph.** `prose_rule_guard.py`
exists to put that question in front of you at the exact moment you are typing
the paragraph, because that is the only moment at which you have all the context
and none of the discipline.

The honest corollary matters just as much: some rules cannot be mechanised, and
the right move there is to keep the prose *and say out loud that it is
unenforced*, so the reader knows what they are relying on. A rule that never
fires is worse than an admitted gap, because it looks like the problem is
handled. The example rule table ships with a `_not_convertible` entry recording
one such attempt and why it failed.

## The rule table lives outside the hooks directory, and that is a load-bearing decision

In my setup a guard protects everything under the hooks directory from being
edited by the agent, for the obvious reason: those files decide what the agent
is allowed to do. But the first version of the output rules lived there too, as
data inside the code. The effect was that adding one rule required a human to
unlock the directory, which meant it never happened at the moment of
annoyance, which meant the conversion from prose to check never took place, and
the whole mechanism was decorative.

Splitting them fixed it. **Code is dangerous and stays locked; data moves out to
where it can be edited the second a rule is learned.** The generalisation is
worth carrying: whenever a safety mechanism makes the safe action expensive, the
safe action stops happening, and the mechanism has made things worse. Look for
the split between the part that must be protected and the part that must be
cheap to change.

## Never fail silent

The first version of the guard returned an empty rule list when it could not
read the table. That looks like the safe choice, do not block the user over a
configuration problem, and it is the most dangerous behaviour in the file. One
misplaced comma disables every rule, with no message, and the setup looks
exactly as it did when it was working. "No rules configured" and "the rules
failed to load" were indistinguishable from the outside.

Now a missing table, a syntax error, an unknown kind, a broken regular
expression, or a `forbid`/`require` rule with no `negative` all stop the turn.
The reason this is acceptable is that the fix is in a file the agent can edit
immediately: you get stopped, and thirty seconds later you are unstopped. The
one thing that still fails open is an unreadable transcript, because that is the
harness misbehaving rather than the author, and there is nothing the author can
do about it.

The `negative` requirement comes from the same instinct applied to a different
risk. This check runs on **every message**, so a rule whose net is too wide does
not fail visibly, it just interrupts unrelated work every day until you turn
the whole thing off. Requiring an example sentence that must *not* fire, and
verifying it at load time, makes the width of the net something you have to
state rather than something you discover. When a real false positive shows up
later, pasting that exact sentence into `negative` guarantees it can never come
back, and leaves a record of what the rule learned.

## Why the preflight looks back exactly seven days

The guard is a Stop hook, so it fires after the message is written. It detects
and does not deter. Over one six-day stretch my top five rules fired 30, 27, 25,
25 and 14 times, on six days out of six. The hook's own text says "if you are
told this twice, add a rule", and the firing did not stop, which is how I knew
the problem was not a missing rule. Adding another one would have stopped in
exactly the same place. What was needed was a change of route: something in
front of the writing rather than behind it.

The window is what makes that affordable. The whole table cannot be injected
every turn, it only grows, and it would tax every turn forever. What can be
injected is the list of rules you actually broke this week, which is short by
construction and, more importantly, **empties itself**. A rule you have fixed
drops off after seven quiet days without anyone deciding to prune it. The
two-distinct-days requirement separates a habit from one bad afternoon; without
it, a single unusual session pins a rule to the list for a week.

Seven days is not a discovery. It is one week, which is the shortest period over
which a habit is distinguishable from an accident, and short enough that the
list turns over while you still remember the sessions in it.

## Two lines for the handoff, not one

One turn costs roughly a tenth of the current context in cache reads before any
work happens, and context only grows, so an *n*-turn window costs about *n²*.
Restarting costs one session baseline plus writing the handoff. At 300k that is
paid back in under three turns; at 150k, in under seven.

That arithmetic gives a threshold, but a single threshold cannot work. Put it
early and it gets ignored, because it always arrives mid-task and the honest
answer is "not now". Put it late and the expensive turns have already been paid
for. So there are two: a soft line where you are asked to hand off **only if the
work is at a seam**, and a hard line where you are asked unconditionally. The
soft line gives the reminder a version that can be obeyed without abandoning
work, which is what keeps it from being trained into background noise.

The escalation exists for the same reason. The nag was measured being ignored up
to seven times in one session while that session ran past 600k. Repeating
yourself at 600k is not free, the reminder is charged at the context that made
it necessary. After three ignored nags, the cooldown widens and the wording gets
blunter, instead of paying full price to say the same thing forever.

The session-start half has a separate lesson. It used to print one pointer: the
most recently modified handoff. Measured across several hundred transcripts, of
259 such hints only 41% were followed, and 16% were ignored while the session
went and opened a *different* handoff, the pointer had guessed the wrong
track. Several threads running at once is the normal case, so modification time
can never key this correctly, and no better ranking exists. The fix was to stop
guessing and print the list, with one living file per track overwritten in
place. The previous convention, one dated file per handoff, had grown to a
couple of hundred files with no way to tell which was current, which is the
failure that convention was invented to solve.

## The memory index has a budget because it is paid for on every turn

Memory splits into two layers with completely different economics. The files can
be as long as they need to be, because they are read only when something needs
them. The index is injected into every session, so every line in it is charged
on every turn, forever.

That is why the index carries names and not contents: a date or a number in the
index goes stale there, and nobody notices, because nobody diffs an index
against its files. And it is why there is a hard budget (110 lines / 18000
bytes) with an archive underneath it. Past that size something worse than cost
kicks in, **the index starts being skimmed instead of read, at which point a
longer index conveys less than a shorter one would have.**

The lint that watches all this is deliberately a detective and not a corrector.
It flags dead links, orphans, drift, dormancy, expired dates and oversize, and
then it stops; a human or a session decides. Two design choices keep it usable:
it says nothing at all when the index is clean, which is the only reason it can
run at every session start, and a false positive is silenced by writing
`lint-ok` on the line. An escape hatch that costs one word gets used. One that
costs a configuration change does not, and then the whole lint gets switched off
instead, which is how a mechanism dies without anyone deciding to kill it.

What the lint cannot do is the part that matters most: notice that two files
contradict each other, or that a durable fact is buried in a file about
something else. No pattern finds those. That is what the periodic
read-it-all-with-fresh-eyes review is for, and the lint's last bucket is the
reminder to do it, the one check that is about your attention rather than the
directory's contents.
