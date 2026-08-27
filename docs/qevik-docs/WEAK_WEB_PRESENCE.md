# Evidenced weak web presence

**Status:** built, tested, deployed.
**Acceptance:** `infra/verify_weak_web_presence.py` — 43 checks.

Turns the responses a verification mission already recorded into findings, and
findings into an opportunity `offer-website` can execute.

| file | role |
|---|---|
| `opportunity/detectors/website.py` | the rules, and `PageObservation` |
| `opportunity/verification.py` | reads recorded evidence into observations |
| `opportunity/detect.py` | `weak_web_presence`, `ANSWERED_BY`, `answerable` |
| `fabric/recipes.py` | `audit="website"` on `verify-recorded-websites` |
| `mission/toolrunner.py` | `_audit`, `targets_map_for` |
| `opportunity/repository.py` | `businesses_by_website` |
| `mission/recurrence.py` | `rec-nightly-website-verification`, 05:00 UTC |

## The problem it solves

`verify-recorded-websites` fetched real homepages through the guarded fetcher
and stored what each server said. Nothing read any of it. Real evidence, with
provenance, producing no conclusion.

## The join

`WebsiteDetector` owned the rules and fetched its own pages with its own httpx
client. Reading stored evidence with a second set of rules would have produced
two definitions of "slow" that agreed until somebody moved a threshold.

Instead the rules were lifted onto a neutral value:

```python
@dataclass(frozen=True)
class PageObservation:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    elapsed_seconds: float
    bytes: int
    body: str
    body_complete: bool = True
```

`inspect()` builds one from a live response. `verification.observation_from()`
builds one from `Evidence.observed`. Both call `findings_from()`. The harness
proves the two paths return the same finding kinds for the same page.

## What the evidence may not support

### A refusal is not a response

`crawler.fetch_steps` records blocked addresses, robots exclusions and dead
hosts as evidence — status 0 with an error. `observation_from` raises
`Unreadable` for all of them.

Auditing a refusal would report a business whose homepage **Qevik's own guard**
declined to fetch as a business with a broken homepage.

### A truncated body is not a short page

Bodies are kept to `BODY_KEPT` (256 KB), and one over `MAX_BYTES` is dropped
entirely — arriving as an empty string with a non-zero byte count.

| finding | survives truncation? |
|---|---|
| `no_https`, `slow_response` | yes — not derived from the body |
| `site_unreachable` | yes — the status is not in the body |
| `missing_title`, `missing_meta_description`, `not_mobile_friendly` | only if `</head>` was reached inside the bytes that arrived |
| `missing_h1`, `no_structured_data`, `thin_content` | **no** |

A JSON-LD block or four hundred more characters of text may sit in the region
that was cut off. `_PageFacts.head_closed` is what distinguishes "this page has
no title" from "the part we kept has none". `</body>` counts as closing the
head, because browsers treat it that way and a reader that does not would
report a missing title on every page that omits `</head>`.

### Evidence of the wrong kind is not weak evidence

A DNS record has no status and no markup. Refused, rather than read with
defaults — defaults are how a missing field becomes a confirmed absence.

## Attribution

By the **requested** URL first, the answering one second. A site redirecting
`example.ae` to `www.example.ae` produces evidence whose source is the second
while memory holds the first.

`_key()` normalises scheme and a trailing slash — exactly what a redirect
changes — and nothing more. Dropping `www` or ignoring the path would merge two
addresses a business may run as different sites.

A response no business claims is attributed to **nobody**. The addresses came
from memory, so an unmatched one means memory changed under the run.

### One query, not two

`businesses_by_website()` returns the addresses and their owners together, and
`recorded_websites()` is derived from it. Two bounded reads of a changing table
— one to decide what to fetch, one to decide whose site it was — would audit
forty sites and attribute thirty-eight, silently.

## The signal

Fires above `WORTH_RAISING = 2` on summed severity. One missing meta description
is a note, not a reason to approach a business.

- Every observation carries the **recorded response** first, so the first
  fingerprint a reader follows lands on what the server actually said.
- Confidence is the **minimum** across findings, not the mean: an inference
  resting on a near-certain markup read and one timing sample is only as good
  as the timing sample.
- `estimated_value` is `None` with `value_status="UNKNOWN"`. Never `0`.

## The offer connection

```python
ANSWERED_BY = {
    FindingKind.SITE_UNREACHABLE: "broken",
    FindingKind.SLOW_RESPONSE:    "performance",
    FindingKind.THIN_CONTENT:     "thin_content",
}
```

`answerable()` intersects these with what `offer-website` **declares** it
answers. When the intersection is non-empty the action is `OUTWARD` with
`needs_approval=True`, naming `offer-website`. When it is empty the signal still
exists — the defects are real — and its action stays inside Qevik.

Six finding kinds map to nothing: no viewport, no title, no meta description, no
structured data, no h1, plain HTTP. Widening `offer-website.answers` is a
reviewed decision. See **Open product decisions** in `MASTER_STATE.md`.

## The declaration

`audit` is a key on the recipe, validated at import against `Recipe.AUDITS`, and
refused when declared without `targets_from` — an audit reads one business's own
server's reply and needs a business to attribute findings to.

An audit is not an extractor. An extractor turns a **source's** statements into
a sighting. An audit turns a **business's own server's** reply into findings
about that business. Only the second can produce something Qevik would approach
somebody about.

## Schedule

`rec-nightly-website-verification`, 05:00 UTC — after the 04:15 discovery, so a
business found tonight is audited tonight. Separate from discovery because the
two are bounded by unrelated numbers and fail differently: Overpass being down
must not stop Qevik auditing the sites it already knows.
