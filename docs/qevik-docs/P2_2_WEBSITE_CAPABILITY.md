# P2.2 — Website creation and modification

The first capability to run the whole loop:

```
Research → Evidence → Opportunity → Recommendation → Roadmap → Website task
  → Execution approval → Generation → Asset provenance → QA
  → Preview / Stage → Artefact approval → Publication → Measurement hook
```

Every join already existed. P2.2 adds **one executor and one offer**, and the
rest is the machinery from P1.2 through P2.1 doing what it was built for.

---

## 1. Files changed

| File | |
|---|---|
| `execution/capabilities/website.py` | new — the capability |
| `execution/artefacts.py` | new — one bundle-hashing rule |
| `tests/test_website_capability.py` | new — 24 tests |
| `execution/capabilities/__init__.py` | registers it; declares the `Executor` shape |
| `recommendation/offers.py` | `offer-website` |
| `execution/service.py` | speaks bundles; threads the `Business` record |
| `execution/capabilities/portfolio.py` | accepts the record it does not use |
| `roadmap/service.py` | `OFFER_DIMENSION` entry + an import-time drift guard |
| `roadmap/crossing.py` | threads the record; `TYPE_CHECKING` import |
| `publication/gate.py` | hashes files with the shared function |
| `tests/test_roadmap.py`, `tests/test_publication.py` | assert invariants, not literals |

**No schema or migration changes.**

## 2. Systems reused

`website/content.py` and `website/generation.py` — the M015 Website Factory,
including the rule this capability depends on entirely: **no fabricated business
facts on a published site**, enforced by a `FactSource` enum with no `GENERATED`
member and a renderer that omits what nobody supplied. `website/themes/clean`.
`outreach/opportunity` rules. `CapabilityOffer`. `EXECUTORS`. The execution
approval, `Run`/`Job`/`Asset`, the six QA gates, `stage()`, the artefact
approval, `PublicationRecord`, `measurement.open_baseline`, tenancy.

Nothing new in any of those categories.

## 3. Capability definition

`offer-website` answers `performance`, `broken` and `thin_content` — the three
website opportunities that had **no offer at all**, so a customer could be shown
the problem and told nothing. Only `discovery` and `maps` remain unanswered, and
both are discovery-family rather than website work.

It deliberately does *not* answer `reachability` or `whatsapp`:
`offer-one-tap-contact` already does, and two offers claiming one gap is how a
customer is sold the same fix twice. A test asserts the answer sets are
disjoint and that no contact feature appears in `FIXES`.

### Two modes, neither chosen by a caller

| Mode | When | What it does |
|---|---|---|
| `CREATE` | research could not read a site | builds one from the business record |
| `MODIFY` | a site exists | adds only what research confirmed **absent** |

`mode_for(research)` derives it from the HTTP status and whether a website was
recorded. `build_website` has no `mode` parameter, and a test asserts that:
letting a caller declare "create" is how a business with a working website gets
a new one built over the top of it.

### The refusal is the point

`build_website` **raises `NothingToBuild`** when a site already does everything
this capability could add. That is `STRONG WEBSITE + LIMITED WEBSITE
OPPORTUNITY` expressed where it cannot be argued with: no artefact exists, so
there is nothing to approve, publish or bill for.

`improvable()` reads only `not_found`. A feature nobody checked is not a gap —
it is a gap in our knowledge, and building against it would manufacture a
weakness. A site whose every feature is `unverified` produces nothing.

## 4. Execution path

`crossing.execute_task` → `execution.execute` → `EXECUTORS["offer-website"]` →
`website.generation.generate` → QA → `READY_TO_PUBLISH`.

The `Business` record is threaded through so facts have a source. Research
detects *whether* a phone number is tappable; it never extracts the number, so
contact facts come from `BUSINESS_RECORD` and service names from `OBSERVED`
pages the business publishes. Nothing else is written.

### One hashing rule

A capability may produce one document or a whole site. `execution/artefacts.py`
normalises both to a bundle — a single document is a bundle with one entry — and
`bundle_hash()` is the only identity function. Two rules would drift, and the
drift would be silent in the worst place: the publication gate compares the
bytes about to go out against the hash that was approved, so a hash computed one
way at execution and another at publication would either refuse everything or,
far worse, **refuse nothing**.

The QA gates now read every page joined, not just the index. A gate reading one
document of a bundle would pass a site whose third page says something
forbidden.

## 5. Asset provenance

The existing metadata plus, from this capability: `mode`, `addresses` (what the
build responds to, each checkable against the research record), `left_alone`
(what the site already does), `not_published_for_want_of_a_source`, `theme`,
`facts`, `fact_sources`, `sections`, and `files` — the bundle's shape, so a
reviewer can see a site was produced rather than a page without fetching it.

Saying what was left out is deliberate. A short page is otherwise
indistinguishable from a broken generator; this says *a phone number is missing
because nobody recorded one*.

## 6. QA

The six existing gates, unchanged. The `capability_output` gate checks each
declared output is present in the artefact, which forced an honest declaration:
`outputs=("a page with a title",)`. A contact section would fail for a business
with no recorded contact details, and the right response to that is a shorter
declaration, not a weaker gate.

## 7. Preview / staging

`stage()` puts the bundle at the target without serving it, and its
`preview_url` goes into the artefact approval payload. A test asserts that after
staging, `current` does not exist — **staging makes nothing live**. This is what
the publish/promote split in `website/targets` was designed for, finally used
for it: the approver looks at the real page on the real host rather than at a
content hash.

## 8. Artefact approval and publication

Unchanged from P2.1. The execution approval authorised building; the artefact
approval authorises this exact bundle reaching this exact destination. A test
publishes a real site to a local target and reads the live file back.

## 9. Measurement hooks

The task carries `metric_key` (`technical_health` via `OFFER_DIMENSION`), the
record carries `completed_at` — exactly the `intervention_at` that
`close_measurement()` needs. `open_baseline` with no reading yet reports
`UNKNOWN`, and `record.is_business_result` is `False`. Publishing a site is an
intervention.

**A drift guard was added at import**: every offer must have an `OFFER_DIMENSION`
entry, or the module refuses to load. Without it, adding an offer produced tasks
with no dimension and no metric — they scheduled, were approved, executed, and
nothing could ever be measured about them. That is exactly what happened while
building this, and it was silent.

## 10. Tenant enforcement

Unchanged and inherited: the roadmap task, the recommendation, the asset, the
connection and both approvals are each checked independently. A test confirms
another tenant cannot execute the website task or see the connection.

## 11. Negative controls — 24 tests

Offer and executor agree · no gap claimed twice · mode is derived and cannot be
declared · a strong website produces no artefact **and** no roadmap task ·
unverified is not a gap · what the site already does is left alone · no
`FactSource` means "a model wrote it" · a business with no recorded details gets
a page without them (and without invented copy) · service names come only from
published pages · a nameless business is refused · both modes produce a real
bundle · the build is deterministic · a single document hashes as a bundle · a
renamed file is a different bundle · nothing publishes without the artefact
approval · staging makes nothing live · another tenant cannot execute it · the
QA gates read every page.

**Full suite: 2185 passed, 25 skipped.** ruff 26 (baseline 43), mypy 135
(baseline 135) — P2.2 adds none of either.

## 12. Two tests corrected

`test_two_different_businesses_do_not_get_the_same_roadmap` asserted a literal
set of shared tasks and broke the moment a capability was added. The claim worth
making is that no *work* is shared — a measurement neither business has had done
and the standing "approve the result" obligation are shared by construction and
say nothing about whether the evidence was read.

`test_a_weakness_with_no_offer_is_shown_and_not_promised` enumerated which
dimensions had no capability. Which ones those are changes every time one is
added; the invariant is that an uncovered weakness is still *shown*.

## 13. Remaining gaps

- **Four offers still have no executor** — Arabic, editorial, imagery, one-tap
  contact. The roadmap is honest about it, and each is a capability plus a QA
  gate, not framework work.
- **The site is one page.** `SiteContent` is medium-agnostic and the theme could
  render a page per service; nothing does yet, so `outputs` claims only a title.
- **CREATE has no opportunity rule.** A business with no website has no audit,
  and a rule firing on the absence of one would make every unaudited business
  look like an opportunity. The mode is reachable through the executor; the
  route from research to a CREATE recommendation is not built.
- **`stage()` is called only in a test.** Nothing in a real flow previews before
  approving, so approvers still see a hash.
- **No scheduler closes the measurement.** `open_baseline` and
  `close_measurement` exist; nothing re-reads a metric 30 days after publication.
- **One target.** Cloudflare and SSH targets exist in `website/targets/` and
  need a `Connection` kind and a resolver each.
