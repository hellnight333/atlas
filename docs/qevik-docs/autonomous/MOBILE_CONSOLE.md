# The console on a phone

*Verified by looking, at 390×844 and 1280×900.*

## What it was

A desktop sidebar turned sideways: fourteen destinations in a horizontal
scroller pinned to the top of the screen. Nothing reachable by thumb, most of it
irrelevant on a phone, and the one number that decides whether to keep reading —
*does anything want me* — sat as the second of six identical cards.

## What it is

**An answer, then reference.** The top of the screen states it in a sentence, in
the display face:

> **1** thing needs you.
> 1 waiting for approval

Deliberately not a seventh card. A card would join the rhythm of the six below
and stop being an answer; the hierarchy comes from the face and the size, which
is what a display role is for. "Nothing needs you" is good news and does *not*
wear the attention colour.

**Four destinations in thumb reach.** A fixed bottom bar: Needs me · Missions ·
Chat · More, ordered explicitly rather than by position in `PAGES`, so adding a
fifteenth page cannot silently change what the bar shows. Everything else lives
behind More — including sign-out, which was only in the rail the phone hides.

Both labels are emitted and CSS chooses between them. Swapping text in
JavaScript would tie the label to the width *at render time* rather than at
paint, so a rotation would leave the wrong one.

## Colour

The console used `#4c8dff`, a generic admin blue matching nothing in this
repository. It now uses `#0d6e6b` — the actual mark, the same value as the
public site's `theme-color` and logo fill — with neutrals biased green rather
than pure grey, because a neutral that sits under the brand all day and was
never chosen reads as inherited.

Semantic colour is kept off the accent: `--signal` amber means *a person is
needed* and must never be confusable with *selected*. Every status still carries
a word as well as a hue.

## Three defects found by looking

None of these were caught by a test.

**`COST` rendered the string `undefined`**, and the underlying behaviour was
worse: with nothing priced, `known_total` is `0.0`, so the card would have shown
**0** — reading as *this was free*. A missing measurement is not zero, and the
UI was the one place still able to imply it was. It now reads `UNKNOWN` with
"2 call(s) reported no cost. This is not zero."

**The badge sat on the wrong destination.** It counted only blocking credential
actions, so a mission awaiting approval badged *Missions* and left *Needs me* —
the item literally labelled for it — empty. The screen disagreed with itself
about whether anything wanted the operator.

**Sign-out was unreachable on a phone.** It lived only in the rail that the
phone layout hides, so the only way out of a session was clearing browser
storage.

## Two defects in the verification, not the page

Worth recording because both produced confident wrong conclusions.

**I reported a horizontal overflow that did not exist.** Chrome's old headless
mode lays the page out at a default width and crops the image to
`--window-size`, so content *looked* clipped at 390px. Measuring the DOM gave
`doc.scrollWidth 390` against a 390 viewport with zero elements exceeding it.
The capture now renders the console inside an iframe of exactly the target
width, which is not subject to whatever the browser does with its window.

**The stub served the wrong endpoint.** It matched fixtures by prefix in
insertion order, so `/api/missions/costs` was answered with the *missions list*
because `/api/missions` was declared first. A stub that answers the wrong
endpoint produces a screenshot of a page that cannot exist. Exact match first,
then longest prefix.

## Running it

    python3 infra/screenshot_console.py --page dashboard
    python3 infra/screenshot_console.py --page dashboard --measure

`--measure` names every element wider than the viewport. It exists because
guessing at CSS from a picture is how an afternoon disappears.

The console is served **unmodified** — a wrapper page seeds the session token,
so nothing in the shipped artefact knows the harness exists. A screenshot of a
file with a test hook in it is a screenshot of a different file.

## Not done

- Only the dashboard was designed to the phone. Mission detail, Chat and
  Credentials render acceptably at 390px but have not been given the same pass.
- No voice, no push notification.
- The `.screenshots/` directory is git-ignored: the decision lives in the CSS,
  not in a PNG.
