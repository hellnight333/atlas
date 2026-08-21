---
name: design-pass
description: Use before building or changing any user-facing surface in this repo — the control dashboard, a portfolio sample, qevik.ai, or any generated site. Loads the project's own design system, forces a written design plan, and applies a review checklist built from mistakes already made here.
---

# Design pass

A surface built without this reads as competent and anonymous. That has already
happened in this repo: the sales dashboard was shipped as a dark sidebar, a
light workspace, white rounded cards and a blue accent — the most common admin
template in existence — while `docs/DESIGN_SYSTEM.md` sat unread in the same
repository.

## 0. Read what already exists. Always. First.

```
docs/DESIGN_SYSTEM.md          the visual and interaction grammar
docs/qevik-docs/50_BRAND.md    positioning and naming
apps/public/build.py           the public site's live palette and type
```

The precedence is fixed: **the user's words → this repo's system → your
choices.** You may only invent where the system is silent, and where you do,
say so in the plan.

If the surface is a portfolio sample, also run `infra/differentiation.py` first
and read what the existing samples already occupy. Do not re-occupy it.

## 1. Write the plan before the code

Four lines, in the response, before touching a file:

- **Subject** — one concrete subject, its audience, and the single job of the page.
- **Colour** — 4–6 named hex values, each with the role it plays.
- **Type** — at least two faces mapped to the system's roles (Display,
  Interface, Document, Mono). Naming one face for everything is a plan that
  failed.
- **Layout** — the structural idea in one sentence, and what makes it *not* the
  obvious one.

Then read the plan back and ask: *would I produce this same plan for any other
page of this kind?* If yes, it is the default, not a design. Change it and say
what you changed.

## 2. The checklist that comes from real mistakes here

Each line is something that shipped wrong in this project.

**Hierarchy**
- [ ] The primary task has dominant visual weight. A message draft and a
      reference table must not wear the same card.
- [ ] There are at most two levels of "card". A column of eight identical
      panels has no hierarchy, only rhythm.
- [ ] Elevation is used: base plane, working plane, overlay. One flat style
      everywhere throws away a whole axis of meaning.

**Type**
- [ ] A display face exists and is used sparingly, distinct from the interface
      face.
- [ ] Numbers that align in columns use `font-variant-numeric: tabular-nums`.
- [ ] Uppercase micro-labels carry letter-spacing; body copy does not.

**Colour**
- [ ] Semantic colour (success / warning / critical) is separate from the
      accent and never borrows it.
- [ ] No status is carried by hue alone — a glyph or a word carries it too.
- [ ] Neutrals are chosen, not inherited. A pure mid-grey reads as unconsidered.

**The three-state rule (non-negotiable in this project)**
- [ ] `CONFIRMED_PRESENT`, `CONFIRMED_ABSENT` and `NOT_VERIFIED` are drawn three
      distinct ways; `REFUTED` a fourth.
- [ ] `NOT_VERIFIED` never borrows the styling of an absence. Painting it red
      invents a finding somebody then repeats out loud to a stranger.

**Avoiding the AI-default look**
- [ ] Not: warm cream + serif display + terracotta accent.
- [ ] Not: near-black + a single acid-green pop.
- [ ] Not: purple-to-blue gradient hero on white.
- [ ] Not: Inter or Space Grotesk chosen because they are safe.
- [ ] Not: emoji as section markers; not everything centred; not `border-radius`
      identical on every element.
- [ ] Numbered markers (01 / 02 / 03) only where the content is genuinely a
      sequence.

**Mobile is a design, not a fallback**
- [ ] Designed at 390×844 first, then verified at 1280×900.
- [ ] Zero horizontal overflow at both. Verify in a browser; do not assume.
- [ ] The primary action is reachable by thumb.

## 3. Verify by looking, not by asserting

Screenshot it and read the screenshot. Every visual defect in this project was
found this way and none were found by tests:

- a completion bar escaping its card (`<h3>` inside a `<button>`)
- a disclosure banner covering the language button so it could not be clicked
- the app shell visible before sign-in (`[hidden]` styled, `.hidden` used)
- a chart legend printing "Best 180" where the plotted value was zero
- both direction buttons rendering the same arrow in Arabic

Then drive it. A rendered page is not a working one.

## 4. Arabic and RTL, if the surface has it

- [ ] Authored, not machine-substituted; not mirrored English.
- [ ] `dir="rtl"` on the document, and the layout genuinely flips.
- [ ] Latin runs, phone numbers, URLs and language codes isolated `ltr`.
- [ ] No arrow glyph between an Arabic and a Latin run — it is a bidi neutral
      and reorders. Use words in Arabic, arrows in English.
- [ ] Off-screen positioning uses vertical offsets, never `left:-9999px`.

## 5. Before saying it is done

- [ ] The plan from §1 is in the response, and the code follows it.
- [ ] Screenshots reviewed at both viewports.
- [ ] Every interactive element driven at least once.
- [ ] Anything left undone is named, not omitted.
