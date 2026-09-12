# Reporting standard

Anything a human might read (a report, a status file, an email, a summary, a
message in a chat) follows this. Condensed English version of a longer
internal document.

## The principle, in one line

**Design for the reader's first thirty seconds. Move your audit trail off their
path.**

When you write, the question is not "will this survive scrutiny". It is "can a
person who has never seen this get the verdict and the next action out of it in
thirty seconds". Both are achievable; it is a question of order, and the audit
material goes further down.

## Eight rules

1. **Verdict first.** The conclusion, the judgement, the next action go at the
   top. A structure where the reader has to finish the document to learn the
   answer is a violation. Make the verdict visually distinct (bold, a callout,
   a table).

2. **Governance material goes to the back.** Self-applied quality gates, review
   status, call counters, check identifiers, read-back verification: fold them
   into the end, a collapsed section, or a separate file. This is not "delete
   your audit trail", it is about where it sits.

3. **Write long text where formatting works.** Do not stuff prose into a field
   that cannot render it. In a database, the page body takes the writing and the
   properties take one or two sentences, as much as fits in one row of a table
   view. Long text in a property is unreadable by construction.

4. **Anything that looks like a filename, path, command or URL goes in a code
   span.** Real damage observed: `collect.ps1` had its `.ps` treated as a
   country domain, auto-linked, and the filename was broken in half mid-word --
   across an entire database before anyone noticed.

5. **One question per unit.** One page, one question. Do not join two subjects
   with a slash in the title, and do not mix a technical question with an
   operational record at the same level.

6. **Define internal terms where they appear.** The names of your own metrics,
   thresholds and bands mean nothing outside your own instrument panel. If you
   use one, gloss it **in one parenthesis, right there**. Building a glossary
   section instead is a violation, because it makes the reader's eyes travel.
   - Bad: *"the ratio is 2.09 -> 2.35, over the proven band of 1.25"*
   - Good: *"the **ratio** (= weekly load divided by what maintenance would
     need; 1.0 is exactly break-even) came in at **2.09 measured**, and today's
     plan lands it at **2.35 predicted**. The band held for two years tops out
     at 1.25."*
   - **When the same symbol appears at two points in time, say what each one
     is.** Joined by a bare arrow, a reader sees "it went up", and one of
     those two numbers had not happened yet.
   - Numbers that carry the verdict carry their provenance: measured, planned
     or estimated.
   - This rule is the one that is machine-enforced, by the output rule table.

7. **Do not blend measurement and interpretation in the same voice.** What you
   measured or quoted, and what you concluded from it, must be visually
   separable, a marker like `[measured]` / `[interpretation]`, or separate
   sections. This matters most **when the request stopped at "check" or "have a
   look"**: an assertive analysis is read as a premise the reader has already
   agreed to. Things that default to interpretation unless stated otherwise:
   a count of categories ("there are two kinds"), a priority order, "the real
   one is this", a cause, and **any description of what the reader is worried
   about**.
   - Bad: *"there are three discrepancies and only one is a real bug"*
   - Good: *"[measured] three places differ. [interpretation] I think one is
     worth fixing, your call."*

8. **Emphasis is made by using less of it.** Bold does two different jobs with
   one mark: a **label** (the name of what follows; read down the page they
   form a table of contents) and **emphasis** (this is the most important thing
   here). Mixed, both stop working, because the reader cannot tell which one a
   given mark is.
   - **Labels are short.** Measured against a document people found readable:
     median 3.5 characters, only 3% over twenty. The unreadable one had 14%
     over twenty, because its bold spans were whole sentences, read down the
     page they are fragments, not a table of contents.
   - **Do not bold a whole sentence at the start of a line.** That position is
     where labels live.
   - **Put the emphasis in the section that carries the verdict**, not in the
     preamble. Being first is not the same as being looked at. In one measured
     document the conclusion had *zero* bold and the background had three.
   - Emphasis is not a continuous quantity, so the only way to create a ranking
     is to use fewer of them. A document with ten emphasised things has no
     ranking at all.

Smaller ones:

- **A "how to read this" line** at the top of anything over three minutes long:
  how far to read for what.
- **Do not drop the numbers.** Run names, job ids, counts, quantities that
  carry the verdict survive summarisation, but in a table or a code span, not
  buried in a paragraph.
- **Sort and group by the reader's priority**, not by chronology or by the
  order in which you did the work.
- **Do not explain a term using the term.** If "options" is explained as "go to
  options", a reader who did not know the word still does not.

## What this standard does not cover

It applies to what you put in front of a person. It says nothing about how much
you keep on disk. Those are separate axes, and conflating them designs
information loss into the system: storage is cheap, and what is expensive is
putting things in a context window. Default to keeping it, indexing it, and
loading only what a decision needs. "Nobody reads it" is not a reason to delete
it, and "it can be fetched again" is not either, because fetching again fails
(the source moves, the format changes, the access goes away).

## Read-back check after writing

Having written to something a human will read, open it again and check the form
mechanically, this is not re-evaluating the content:

- [ ] non-empty, with the conclusion at the top
- [ ] zero broken auto-links (a filename that got linkified is a failed write;
      rewrite it in a code span)
- [ ] no long text stuffed into a metadata field
- [ ] governance material is not occupying the opening
- [ ] **you opened it in the form it will be read in**, the rendered page,
      the PDF, the email body. Do not judge from the source. Heading levels,
      how figures land, and where pages break are invisible in the source.

If one of these fails, rewrite **once**. If it still fails, record it honestly
as a failure. Do not log a success.
