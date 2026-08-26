# From a fetched page to an actionable opportunity

The chain, end to end:

```
rec-daily-business-discovery
  -> scheduler tick          (unattended; origin `none`)
  -> mission                 (names recipe + role)
  -> research role           (--agent research, no model credential)
  -> discover-dubai-dental-osm
  -> http-fetch              (budget, robots, SSRF on every redirect hop)
  -> Evidence                (URL, status, timing, bounded body, fingerprint)
  -> extractor               (declared fields only)
  -> Sighting
  -> resolve against memory  (strong keys only)
  -> classify                (KNOWN / NEW_TO_QEVIK / DISCOVERED_BY_QEVIK / PROVEN_NEW_TO_SOURCE)
  -> detect                  (only what the evidence supports)
  -> rank                    (deterministic, explainable)
  -> persist + report + API
```

## The extractor is a declaration, not a parser

The obvious implementation reads a response and returns whatever it can find.
That is also the implementation where, six months from now, a model is handed a
page and asked to "pull out the business details" — and a `Sighting` arrives
whose name came from a heading and whose country came from a guess.

So an extractor **declares which fields it can produce**, and a field it does
not declare cannot appear. `Field_(name=...)` is validated against `Sighting`'s
own fields, so a rule naming something that does not exist fails at import.

OpenStreetMap first because it is public, free, needs no credential, and answers
in **structured JSON** — extraction is a declared mapping from named keys, not a
model deciding what looks like a business name.

## Absence has three answers

| | |
|---|---|
| `OBSERVED` | the source stated a value |
| `ABSENT_IN_SOURCE` | the source was consulted and had none |
| `NOT_CONSULTED` | this extractor does not read that field at all |

`NOT_CONSULTED` is the one that matters and the easiest to omit. A field nobody
looked for is not a field that is missing, and a detector treating them alike
produces *"this clinic has no phone number"* about a source that was never
asked.

The whole `UNVERIFIED_WEB_PRESENCE` detector rests on this: OSM lacking a
`website` tag is a fact about **OSM**, so the suggested action is *verify*, not
*sell*.

## Only two detectors, and the absent ones are the point

Built: **new business** (memory had nothing) and **no website recorded by the
source** (a lead worth ten seconds of checking).

Deliberately not built, with the reason each is not yet supportable:

| not built | needs |
|---|---|
| `WEAK_WEB_PRESENCE` | the site fetched and audited — until then "weak" is a guess |
| `MISSING_SERVICE` (real) | a page read |
| `NEW_LOCATION` | two sightings of one business in different places |
| `COMPETITOR_CHANGE` | a competitor set nobody has defined |
| `HIGH_GROWTH_SIGNAL` | a time series. One scan is not a series |

Each becomes buildable the moment its evidence exists. Adding them now would
mean a detector that fires on absence of data.

## Ranking is deterministic, and revenue is not scored

A model asked to order a list will produce one, and it will be plausible, and
nobody will be able to say why one thing came above another six weeks later. So
the score is a weighted sum of five named components, each carrying the sentence
that explains it:

| component | weight |
|---|---|
| evidence | 0.30 (plateaus at 5 — a hundred is not ten times better than ten) |
| confidence | 0.25 |
| recency | 0.20 |
| executable today | 0.15 (read from `EXECUTORS`) |
| specificity | 0.10 |

**Revenue is absent from that table.** Nothing has measured what a dental
practice in Dubai is worth to Qevik. `value` is `UNKNOWN` with **no amount**,
and the column is nullable precisely so a `DEFAULT 0` cannot undo the rule from
a schema definition. A business nobody has valued is not a business worth
nothing.

A model may later explain or enrich an opportunity. It must not become the
authority on whether evidence exists or whether something is new — those are
`extractors.py` and `discovery.py`, deterministic for that reason.

## Two bugs this found

**Every website-less business was recreated on every scan.** `resolve_business`
matches on strong keys only — domain, email, phone — and a business the source
records none of has no strong key at all. A nightly run would have produced one
duplicate per night per business, for ever. Found by scanning the same fixture
twice and getting two of everything.

The source's stable id is now a **`source:`** key, namespaced
(`source:openstreetmap:node/9002`). Deliberately *not* `place:`: that prefix
carries "a different physical location, overriding every other agreement" — the
rule that stopped one clinic's three branches becoming one record. Giving every
source id that meaning would stop two mapping providers ever agreeing on one
business, because their ids necessarily differ. The first attempt used `place:`
and broke exactly that, caught by the discovery harness.

**`atlas_opportunities` already existed.** It holds the findings-based funnel
`Opportunity` (niche, stage, finding_ids), which is a different thing from a
detected `Signal`. `CREATE TABLE IF NOT EXISTS` silently did nothing and the
index failed on a column the existing table has never had. The new table is
`atlas_signals`, named after the model it stores.

## Proven on real data

A real production worker run on `qevik-core-01`, against the real Overpass API:

```
mission: complete
59 sightings recorded    real Dubai dental practices, several Arabic-named
112 opportunities        59 new_business + 53 no-website-recorded
                         every one with evidence fingerprints, worth UNKNOWN
```

### The third bug: the crawler impersonated a browser

`USER_AGENT` was `Mozilla/5.0 (compatible; QevikResearch/1.0;
+https://qevik.ai/crawler)`. Overpass answers that with **406 Not Acceptable**,
and the first real run failed on it — with the extractor correctly refusing the
HTML error page rather than reading it, which is the guard doing exactly its job.

Two guesses were wrong. It was not the `Accept` header, and it was not only the
`Mozilla/5.0` prefix. Varying one token at a time isolated it: the word
**`crawler`** in the URL. `/bot` and `/research` both return 200 with an
otherwise identical string.

Now `QevikResearch/1.0 (+https://qevik.ai/research; research@qevik.ai)` — which
is also the courtesy every crawling policy asks for: an operator whose logs we
appear in can find out who we are and tell us to stop.

## Surface

`GET /api/discovery/opportunities` — best first, four parts kept apart, every
inference carrying `is_an_inference` in the payload so a renderer cannot forget.
`GET /api/discovery/opportunities/{id}` for one. Both GET; the surface offers no
way to execute anything.

No demo rows. An empty list means the scan ran and found nothing new.

## Verifying a website: targets from memory, never from a proposal

Verification is inherently per-business, and recipes have no variables. The
collision is resolved by `targets_from`, which is not a parameter: the addresses
come from Qevik's **own memory**, every one put there by an evidenced sighting.
A model cannot widen the allow-list because a model cannot write a sighting.

`verify-recorded-websites` fetched 40 recorded sites on real data — 37 answered,
3 did not — recording status, protocol and timing for each. That is the evidence
that turns "the source lists a website" into "the website answers, or does not".

**Verifying that a business has no website is a different problem** and is not
this recipe. It needs a search provider to look for one, which is a real
external dependency and is recorded as one rather than guessed at.

### `Budget` is per prospect, not per pass

`Budget` is "what one prospect is allowed to cost" — forty pages deep into one
site. Sharing it across forty *different* businesses exhausted it, and every
target after the fortieth page was refused: a run that fetched real results and
then reported failure. `fetch_steps(..., per_target=True)` gives each address a
one-page allowance, and the bound on the run is the number of targets.

A refusal is still evidence. An **address-guard** refusal fails the step,
because it means the recipe was pointed somewhere it must not go. Anything else
— a site that will not answer, a robots policy — is one target out of many, and
failing the whole pass because the fortieth site was down would throw away
thirty-nine real results.

## Files

| Path | What |
|---|---|
| `opportunity/extractors.py` | declared, typed reading of one source |
| `opportunity/detect.py` | the two supported detectors |
| `opportunity/ranking.py` | deterministic, explainable ordering |
| `packages/kernel/tests/test_extractors.py` | 20 tests |
| `packages/kernel/tests/test_detect_and_rank.py` | 20 tests |
| `infra/verify_opportunity_engine.py` | 49 checks, real database, negative controls |
| `verify-recorded-websites` | targets from memory; 40 real sites fetched |
