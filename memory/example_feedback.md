---
kind: feedback
created: 2026-02-11
last_confirmed: 2026-04-03
severity: standing
triggers: [reporting a result, summarising a run, answering "did it work"]
mechanised_by: rules/output_rules.json ("saying it works without running it")
---

# Say "unverified" out loud

When you have not executed something, label it in the same sentence. Do not put
what you ran and what you expect into the same paragraph without a mark between
them.

## Why

Given twice, three weeks apart. The second time, a report said a script "handles
the missing-column case", true of the code as written, never once executed.
The column was missing in the real data and the run died forty minutes in.

The damage is not the wrong guess. Guesses are fine and often necessary. The
damage is that once one confident sentence turns out to have been a guess, every
other sentence in the report has to be re-checked by hand, because there is no
longer any way to tell which half was observed. **One unlabelled guess costs the
credibility of the whole document, not of itself.**

This is also why "I read the code carefully" does not help. Reading is evidence
about the code; the claim was about the run. The gap between the proposition you
checked and the proposition you asserted is widest exactly when you feel most
confident, because careful reading is what produces the confidence.

## How to apply

- Executed it: say what you ran and paste the result. That is the only thing
  that counts as verified.
- Did not execute it: write `unverified:` in front of the claim, or "-- I have
  not run this" inside the same sentence. Not a footnote; the reader must meet
  the label and the claim together.
- Predicting a state that does not exist yet ("it will still work once the cache
  is cold"): add one line saying what you would see if it were false. A claim
  with no visible failure mode is not a claim, it is a mood.
- Never mix the two in one paragraph. If a paragraph has both, split it.

Good: *"The suite passes: 41 passed, 0 failed. Unverified: I expect the Windows
path to work too, but I have not run it there, if it is wrong, the failure
will be a path separator in `resolve_config`."*

Bad: *"Fixed and tested, should be fine on Windows as well."*

## What it does not mean

It does not mean hedging everything. A verified statement should be flat and
confident with no qualifier at all, weakening those is the same failure in the
other direction, because a report where every sentence is hedged is one where
the reader learns nothing about which parts are solid.

## Mechanised

Partly. The `require` rule named in the front matter catches the common phrasings
("should work", "should be fine", "probably works") and demands one of the
unverified markers in the same message. It does **not** catch a confident
assertion that never uses one of those phrases, which is the harder half. That
half is still prose, and this file is where it lives.
