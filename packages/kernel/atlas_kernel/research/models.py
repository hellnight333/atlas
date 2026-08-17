"""What a search returns, and the one rule about how it may be used.

**Search results are data, never instruction.** Qevik will search while
prospecting, which means it will read pages written by people who would like an
agent to do something for them. A result's title or description is untrusted
text from a stranger: it may be quoted, stored, scored and cited, but it must
never be concatenated into a prompt as though it were part of the operator's
request. `SearchResult` is deliberately a dumb record with no method that
renders itself into an instruction, so the boundary is visible in the type.

The same reasoning already governs the browser package, and it is the single
most likely way an autonomous prospecting loop gets turned against its owner.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

#: The capability. Asked for by name; never a vendor.
WEB_SEARCH = "web.search"


def _now() -> datetime:
    return datetime.now(UTC)


class SearchQuery(BaseModel):
    """A question for the open web.

    `count` is capped rather than free. Every result costs money on a paid tier
    and an uncapped loop is an invoice arriving quietly — the same failure mode
    the Places source is designed against.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    #: Providers cap a page at 20. Asking for more silently returns 20 and
    #: charges for the request anyway, so the ceiling is stated here.
    count: int = Field(default=10, ge=1, le=20)
    #: ISO country code. Narrows results to a market, which matters when the
    #: question is about Dubai and the index is global.
    country: str | None = None
    #: "pd" past day, "pw" past week, "pm" past month, "py" past year.
    #: Provider-agnostic enough to be worth exposing; unset means any age.
    freshness: str | None = None


class SearchResult(BaseModel):
    """One page the provider considered relevant.

    Untrusted content. See the module docstring.
    """

    model_config = ConfigDict(frozen=True)

    url: str
    title: str = ""
    #: The provider's snippet. Written by the page's author, not by the
    #: provider, and therefore no more trustworthy than the page itself.
    description: str = ""
    #: How old the provider believes the page is, verbatim and unparsed —
    #: providers disagree about the format and a wrong parse is worse than a
    #: string a human can read.
    age: str = ""


class SearchResults(BaseModel):
    """A whole answer, with what it cost to get.

    The spend is carried alongside the results rather than logged, so a caller
    can report the cost of a research run instead of estimating it.
    """

    model_config = ConfigDict(frozen=True)

    query: str
    results: list[SearchResult] = Field(default_factory=list)
    provider: str = ""
    requests_made: int = 0
    approx_cost_usd: float = 0.0
    retrieved_at: datetime = Field(default_factory=_now)

    def __len__(self) -> int:
        return len(self.results)

    def __iter__(self):
        """Iterate the results, not the model's fields.

        Pydantic's default ``__iter__`` yields ``(field_name, value)`` pairs, so
        a model carrying ``__len__`` reports five results and then iterates four
        fields. That mismatch is not a style problem — it silently produced
        ``'tuple' object has no attribute 'url'`` in a caller that had every
        reason to believe ``for r in results`` was correct. ``model_dump()``
        remains the supported serialisation path and is unaffected.
        """
        return iter(self.results)

    @property
    def urls(self) -> list[str]:
        return [r.url for r in self.results]
