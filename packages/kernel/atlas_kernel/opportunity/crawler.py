"""Recipe steps that are fetches, carried out by the guarded fetcher.

The chain the discovery work is supposed to run down is

    registry -> recipe -> tools -> evidence

and this is the link between *tools* and *evidence*. A recipe step for the
`researcher` agent is not a program to run: that agent declares `http-fetch`
and `dns`, and nothing else. So its steps name **what to fetch**, and this
turns each one into an `Evidence` record.

## Why not a shell step running a scraper

Because the researcher does not declare `shell`, and the honest options were to
widen its declaration to fit the implementation or to fit the implementation to
the declaration. Widening it would have made the tool contract describe what
the code happens to do rather than what the agent may reach — which is the
contract not being a contract.

## Nothing here decides what a fetch means

It returns what the server said: the status, the content type, the size, the
redirect chain and the resolution. Whether a 404 means "no website" or "the
crawler was blocked" is a detector's judgement and lives in `detectors/`. A
fetcher that classified would be a fetcher whose mistakes look like facts.

## The guard is not reimplemented

`research/net.Fetcher` already refuses addresses that are not on the public
internet, on **every redirect hop** rather than only the first, consults robots
before the first request, and spends from a `Budget` that cannot be topped up
by constructing a second fetcher. All of that is used as it stands. A second
implementation of an SSRF guard is a second thing to get right, and the one
that gets skipped is always the copy.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..research.net import Budget, Fetcher, Page, Resolution, host_of, resolution
from .models import Evidence, EvidenceKind


@dataclass(frozen=True)
class Refused:
    """A fetch that was not attempted, and why.

    Distinct from a failed fetch. "The guard refused this address" and "the
    server did not answer" are different facts, and a caller that cannot tell
    them apart will report a blocked private address as a dead website.
    """

    url: str
    because: str

    def as_evidence(self, detector: str) -> Evidence:
        return Evidence(
            kind=EvidenceKind.HTTP_RESPONSE, source=self.url,
            observed={"attempted": False, "refused_because": self.because},
            summary=f"not fetched: {self.because}", detector=detector)


def evidence_from(page: Page, *, detector: str) -> Evidence:
    """What the server said, as a record somebody can re-check.

    `observed` keeps the raw shape. The summary is a convenience and never the
    record of truth — a summarised observation cannot be re-checked, which is
    the whole reason `Evidence.observed` exists.
    """
    return Evidence(
        kind=EvidenceKind.HTTP_RESPONSE if not page.is_html
        else EvidenceKind.HTML_CONTENT,
        source=page.url,
        observed={
            "status": page.status,
            "content_type": page.content_type,
            "bytes": page.bytes,
            "elapsed_ms": page.elapsed_ms,
            "redirect_chain": list(page.redirect_chain),
            "error": page.error,
        },
        summary=(f"HTTP {page.status}" if not page.error
                 else f"failed: {page.error}"),
        detector=detector)


def unreachable(url: str, *, detector: str) -> Evidence | None:
    """Evidence that a host does not exist, when DNS says so **conclusively**.

    Returns `None` for `UNKNOWN`, which is the point: a lookup that timed out
    establishes nothing, and recording it as "no such host" is how a business
    gets reported as having no website because a name server was slow for a
    second. Missing evidence stays missing.
    """
    answer = resolution(host_of(url))
    if answer is not Resolution.NO_SUCH_HOST:
        return None
    return Evidence(
        kind=EvidenceKind.DNS_RECORD, source=url,
        observed={"resolution": answer.value, "host": host_of(url)},
        summary="the host does not exist", detector=detector)


def fetch_steps(urls: list[str], *, detector: str = "recipe-fetch",
                budget: Budget | None = None,
                client: object | None = None,
                check_addresses: bool = True) -> tuple[list[Evidence], list[Refused]]:
    """Fetch each URL through the guard, returning evidence and refusals.

    One `Budget` across every URL, passed down rather than created per fetch:
    every request spends from the same allowance, so a long list cannot quietly
    get itself a bigger one.

    A refusal is returned rather than raised. One private address in a list of
    forty should not abandon the other thirty-nine — it should be recorded as
    the refusal it is, where a reviewer can see which URL was refused and why.
    """
    shared = budget or Budget()
    collected: list[Evidence] = []
    refused: list[Refused] = []

    for url in urls:
        root = f"{'/'.join(url.split('/')[:3])}"
        fetcher = Fetcher(root, budget=shared, client=client,
                          check_addresses=check_addresses)
        try:
            page = fetcher.get(url)
        except Exception as failure:              # noqa: BLE001 - recorded, not raised
            refused.append(Refused(url=url, because=str(failure)[:200]))
            continue
        finally:
            close = getattr(fetcher, "close", None)
            if callable(close):
                close()

        # `Fetcher.get` "never raises for a bad site": a refusal comes back as a
        # Page with `status=0` and an error saying why. Reading that rather than
        # expecting an exception is the difference between recording "the guard
        # refused this address" and recording "this website returned nothing".
        if page.status == 0 and page.error:
            refused.append(Refused(url=url, because=page.error))
            continue
        collected.append(evidence_from(page, detector=detector))
    return collected, refused


def was_refused_by_the_guard(refusal: Refused) -> bool:
    """Whether this refusal came from the address guard rather than the site.

    Named rather than left as a string match at each call site: "address
    refused" is the SSRF guard doing its job and is not a fact about the
    business, and a caller that cannot tell will record a private address as a
    dead website.
    """
    return refusal.because.startswith("address refused")


__all__ = ["Refused", "evidence_from", "fetch_steps", "unreachable",
           "was_refused_by_the_guard"]
