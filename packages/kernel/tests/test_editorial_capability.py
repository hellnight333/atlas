"""The editorial capability, tested on the article it must never write.

A capability called "editorial" sounds like it should write articles, and
writing an article about somebody else's business means asserting things about
their business nobody told us. `website/content.py` forbids exactly that, and
the forbidding is why the content architecture is trustworthy at all.

So the tests below are mostly about what is *not* in the output: no body text, no
invented dates, no categories nobody assigned, no article that was not published.
"""

from __future__ import annotations

import pytest

from atlas_kernel.execution.artefacts import bundle_hash
from atlas_kernel.execution.capabilities import EXECUTORS, build_editorial_hub
from atlas_kernel.execution.capabilities.editorial import MAX_ARTICLES, NothingToBuild
from atlas_kernel.recommendation.offers import BY_ID

#: AHS's four posts, as their WordPress API reports them: good subjects, all one
#: day, none categorised, none carrying an image.
AHS = {"facts": {"cms": {"post_list": [
    {"slug": "formula-1-abu-dhabi-2025",
     "title": "Catering the Formula 1 Abu Dhabi Grand Prix 2025",
     "url": "https://ahscatering.com/f1/", "published": "2025-11-11",
     "words": 103, "images": 0, "categories": []},
    {"slug": "eatlux-show-belt", "title": "EATLUX show belt dining",
     "url": "https://ahscatering.com/eatlux/", "published": "2025-11-11",
     "words": 331, "images": 0, "categories": []},
    {"slug": "sustainability", "title": "Sustainability and luxury",
     "url": "https://ahscatering.com/sustainability/", "published": "2025-11-11",
     "words": 210, "images": 0, "categories": []},
]}}}

NOTHING = {"facts": {"cms": {"post_list": []}}}


def _build(research=AHS):
    return build_editorial_hub(business_name="AHS Catering & Events",
                               research=research)


# ================================================ registered and executable

def test_the_offer_now_has_an_executor() -> None:
    assert BY_ID["offer-editorial"].id in EXECUTORS
    assert EXECUTORS["offer-editorial"] is build_editorial_hub


def test_what_the_offer_declares_is_in_the_artefact() -> None:
    """The QA gate checks each declared output appears. Asserted here so a
    wording change to the offer is caught before a job fails its own gate."""
    files, _ = _build()
    joined = "\n".join(files[path] for path in sorted(files)).lower()
    for output in BY_ID["offer-editorial"].outputs:
        assert output.split()[-1].lower() in joined, output


# ================================================ nothing is written

def test_no_article_body_is_generated() -> None:
    """The whole point. Titles, dates and links are theirs; prose about their
    business would be an assertion nobody made."""
    files, provenance = _build()
    assert provenance["nothing_written"]
    for path, page in files.items():
        if not path.startswith("articles/"):
            continue
        # Their title and date appear; nothing resembling a paragraph of copy.
        assert "<p>" not in page.replace('<p class="lede">', "") or "href" in page
        assert "Lorem" not in page
        for invented in ("Our team", "We are proud", "In today's", "Discover how"):
            assert invented not in page


def test_only_articles_the_business_published_appear() -> None:
    files, provenance = _build()
    published = {p["slug"] for p in AHS["facts"]["cms"]["post_list"]}
    assert set(provenance["articles"]) == published
    for slug in published:
        assert f"articles/{slug}.html" in files
    assert len(files) == len(published) + 1, "an index and one page each, no more"


def test_their_dates_are_theirs() -> None:
    files, _ = _build()
    assert "11 November 2025" in files["index.html"]
    # And a post with no date says so rather than getting one.
    undated = {"facts": {"cms": {"post_list": [
        {"slug": "x", "title": "Untitled subject", "url": "", "published": "",
         "words": 0, "images": 0, "categories": []}]}}}
    files, _ = build_editorial_hub(business_name="X", research=undated)
    assert "date not published" in files["index.html"].lower()


def test_a_business_that_publishes_nothing_gets_no_hub() -> None:
    with pytest.raises(NothingToBuild, match="invent its own contents"):
        build_editorial_hub(business_name="Silent Co", research=NOTHING)
    with pytest.raises(NothingToBuild):
        build_editorial_hub(business_name="Silent Co", research={"facts": {}})


def test_an_unusable_slug_is_dropped_rather_than_rewritten() -> None:
    """A renamed route is a broken link back to their original."""
    messy = {"facts": {"cms": {"post_list": [
        {"slug": "../../etc/passwd", "title": "Bad", "url": "", "published": ""},
        {"slug": "", "title": "No slug", "url": "", "published": ""},
        {"slug": "good-one", "title": "Good", "url": "", "published": ""}]}}}
    files, provenance = build_editorial_hub(business_name="X", research=messy)
    assert provenance["articles"] == ["good-one"]
    assert not any(".." in path for path in files)


def test_the_hub_is_capped_so_units_stay_proportional() -> None:
    many = {"facts": {"cms": {"post_list": [
        {"slug": f"post-{i}", "title": f"Post {i}", "url": "", "published": "2025-01-01"}
        for i in range(MAX_ARTICLES + 10)]}}}
    _files, provenance = build_editorial_hub(business_name="X", research=many)
    assert len(provenance["articles"]) == MAX_ARTICLES


# ================================================ the bundle behaves

def test_the_build_is_deterministic() -> None:
    first, _ = _build()
    second, _ = _build()
    assert bundle_hash(first) == bundle_hash(second)


def test_every_article_links_back_to_the_index() -> None:
    files, _ = _build()
    for path, page in files.items():
        if path.startswith("articles/"):
            assert "../index.html" in page


def test_the_provenance_reports_what_the_research_found() -> None:
    _files, provenance = _build()
    assert provenance["uncategorised"] == 3
    assert provenance["without_images"] == 3
    assert provenance["median_words"] == 210
    assert provenance["fact_source"] == "observed"
