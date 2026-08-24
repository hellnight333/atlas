# Qevik, assessed by Qevik

`python3 infra/run_qevik_self_use.py` · 24 August 2026 · tenant `tenant-qevik`

The point was not to produce a report about ourselves. It was to find out what
the engine says when the subject is a business we cannot be wrong about — every
other subject is a stranger whose site we half-understand, and here the gap
between what the evidence shows and what is true is visible.

Run offline deliberately. Crawling our own site would make the output depend on
whether the network is up, which makes it useless as a record.

## What was put in

0 features confirmed present · 6 confirmed absent · **10 never checked**.

The unverified ones are recorded as unverified rather than assumed. A
self-assessment padded with strengths we did not check would be exactly the
flattery the three-state model exists to prevent, and it would be undetectable
because nobody audits their own file.

## What came out

### Three of eight readiness dimensions have no score at all

```
reachability           0.0   MEDIUM    (2 checked, 0 not)
conversion             0.0   MEDIUM    (1 checked, 0 not)
discoverability          —   UNKNOWN   (0 checked, 5 not)
ai_visibility            —   UNKNOWN   (0 checked, 0 not)
content                0.0   MEDIUM    (2 checked, 0 not)
proof                  0.0   MEDIUM    (1 checked, 0 not)
technical_health         —   UNKNOWN   (0 checked, 2 not)
multilingual           0.0   MEDIUM    (1 checked, 0 not)
```

**This is the most important line in the report.** `discoverability`,
`ai_visibility` and `technical_health` are `None`, not `0.0`. A dimension nobody
measured has no score.

Printing `0.0` there would put Qevik at the bottom of a scale it was never
measured on — and it is precisely the mistake the engine must never make about a
customer, where "your technical health is 0" is a sentence somebody would act
on. The model refuses, in code, and the script had to be written to handle
`None` because the architecture would not produce a comfortable number.

### The engine is conservative with its own opportunities

Six confirmed-absent features produced **three** opportunities, and three
produced **two** recommendations totalling 40 units. Absence is necessary for an
opportunity and not sufficient: something has to be able to execute it, and
`enquiry` did not survive that check.

| | |
|---|---|
| Opportunities | `arabic`, `reachability`, `enquiry` — all HIGH |
| Recommendations | `offer-arabic-experience` (30 units), `offer-one-tap-contact` (10 units) |

### The roadmap starts with something only a person can do

7 tasks: **6 Qevik, 1 customer**. The customer task is first:

```
[customer_task ] Connect Search Console
[qevik_task    ] Measure AI search visibility
[qevik_task    ] Arabic experience
[qevik_task    ] One-tap contact
[qevik_task    ] Give visitors a way to ask for what they want
[qevik_task    ] Publish something worth finding
[qevik_task    ] Turn the work already done into evidence a buyer can check
```

That ordering is the engine working: measurement cannot begin until somebody
connects a data source, and the roadmap says so instead of scheduling work whose
result nothing could check.

### Our own generated site passes our own audit

3 files — `index.html`, `robots.txt`, `sitemap.xml` — and `seo.audit()` returns
clean: every page carries what the detector checks and every internal link
resolves.

`indexable: False`. No domain has been agreed for publication, so the generated
`robots.txt` disallows everything. Correct: we are not published, and a
generator that assumed otherwise would put a preview in an index.

### Nothing unverified became something to sell

Asserted programmatically rather than reviewed by eye: for each of the 10
never-checked features, the script asserts it does not appear in the opportunity
list. **It does not.** An offer justified by a gap nobody looked for is the
failure the whole evidence model exists to prevent, and it is invisible unless
something checks.

## What this says about the product

**The engine works and it is honest, including when the honesty is
unflattering.** It declined to score three dimensions, declined to turn three of
six absences into opportunities, and declined to sell against anything it had
not checked.

**It is also nearly blind about us, and says so.** 10 of 16 features unverified
is not a good position to advise from — which is the finding. The first
actionable item is not "build a website"; it is that we have not measured our
own site, and the roadmap's first task is connecting the thing that would let us.

**Data, not a model, is the gap.** Every refusal above closes the moment real
observations exist. That is a crawl of `qevik.ai` and a Search Console
connection — one is code that already runs, the other is a credential.

## Machine-readable

`qevik_self_assessment.json`, beside this file, carries the same result with
per-dimension scores, confidences and counts.
