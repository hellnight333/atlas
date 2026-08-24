"""Imagery, tested on the lie a generated image can tell.

An image on a business's own website is a claim about that business. A kitchen
photograph on a caterer's site says *this is our kitchen*. A team photo says
*these are our people*. Put a generated image in either place and the site makes
a false statement in the customer's name, to their customers — and unlike
invented copy, nobody reads an image sceptically. It is the most convincing lie
a generated site can tell and the one a reviewer is least likely to catch.

So nearly all of this is refusals, and the important one is that the refusal
cannot be argued out of: the *slot* decides whether an image is a claim, not the
request, so no flag turns a premises photograph into a decoration.
"""

from __future__ import annotations

import pytest

from atlas_kernel.website.imagery import (
    PLACEMENT,
    SLOTS,
    ImageRequest,
    ImageryRefused,
    Origin,
    allow,
    apply,
    check,
    documentary,
    plan,
)


def _request(slot: str, origin: Origin = Origin.GENERATED, **kw) -> ImageRequest:
    return ImageRequest(slot=slot, origin=origin,
                        alt=kw.pop("alt", "A description"),
                        prompt=kw.pop("prompt", "an abstract texture"), **kw)


def _url(request: ImageRequest) -> str:
    return f"/img/{request.slot}.webp"


# ============================================ the claim an image makes

@pytest.mark.parametrize("slot", ["premises", "team", "product", "work",
                                  "equipment", "certificate", "food"])
def test_a_generated_image_is_refused_in_every_documentary_slot(slot) -> None:
    """Each of these says "this is ours". None may be invented."""
    report = check(_request(slot))
    assert report["usable"] is False
    assert "false statement about the business" in report["statement"]


def test_stock_photography_is_refused_in_a_documentary_slot() -> None:
    """A licensed photograph of somebody else's kitchen is still not theirs."""
    report = check(_request("premises", Origin.STOCK, source_url="https://x/y.jpg"))
    assert report["usable"] is False


def test_a_supplied_photograph_is_allowed_where_a_generated_one_is_not() -> None:
    """The negative control: the refusals above are about origin, not about
    documentary slots being unusable."""
    report = check(_request("premises", Origin.SUPPLIED, supplied_by="Ayoub"))
    assert report["usable"] is True


def test_a_generated_image_is_allowed_where_it_claims_nothing() -> None:
    for slot in ("header_texture", "section_pattern", "divider", "background"):
        assert check(_request(slot))["usable"] is True, slot


def test_the_slot_decides_and_the_request_cannot_argue() -> None:
    """One registry. A caller cannot mark a premises photograph decorative to
    get a generated one past the check."""
    assert documentary("premises") is True
    assert documentary("header_texture") is False
    assert set(ImageRequest.model_fields) & {"documentary", "decorative"} == set(), (
        "an image must not carry a flag that overrides its slot")


def test_an_unknown_slot_is_treated_as_documentary() -> None:
    """The safe direction: a slot nobody classified might be a premises
    photograph, and guessing wrong publishes a false claim rather than losing a
    decoration."""
    assert documentary("mystery_slot") is True
    assert check(_request("mystery_slot"))["usable"] is False


def test_every_slot_in_the_registry_is_classified() -> None:
    assert all(isinstance(v, bool) for v in SLOTS.values())
    assert any(SLOTS.values()) and not all(SLOTS.values()), (
        "both kinds must exist or the distinction is decorative itself")


# ============================================ provenance and accessibility

def test_an_unsigned_photograph_is_refused() -> None:
    """It cannot be queried when it turns out to be the wrong building."""
    report = check(_request("premises", Origin.SUPPLIED))
    assert report["usable"] is False
    assert "cannot be queried" in report["statement"]


def test_a_generated_image_with_no_prompt_has_no_provenance() -> None:
    report = check(ImageRequest(slot="divider", alt="A line", prompt=""))
    assert report["usable"] is False
    assert "no provenance" in report["statement"]


def test_an_image_with_no_alt_text_is_refused() -> None:
    """A missing alt is a defect Qevik detects on other people's sites."""
    report = check(ImageRequest(slot="divider", alt="  ", prompt="a line"))
    assert report["usable"] is False
    assert "invisible to part of the audience" in report["statement"]


def test_the_markup_carries_its_own_provenance() -> None:
    """The question "is this photograph real" is asked while looking at the
    page, by somebody who has never seen the report."""
    image = allow(_request("header_texture", provider="mock", model="m1"),
                  url="/img/h.webp")
    markup = image.markup()
    assert 'data-provenance="generated:mock/m1"' in markup
    assert 'alt="A description"' in markup
    assert 'loading="lazy"' in markup


def test_a_supplied_photograph_is_marked_as_supplied() -> None:
    image = allow(_request("premises", Origin.SUPPLIED, supplied_by="Ayoub"),
                  url="/img/p.jpg")
    assert 'data-provenance="supplied"' in image.markup()


def test_an_attribute_cannot_break_out_of_its_quotes() -> None:
    """The property that matters, stated as itself.

    An earlier version stripped `&quot;` from the output and then asserted the
    payload was absent — which is the test undoing the escaping and then
    complaining it was gone. What must hold is that no raw quote or angle
    bracket survives inside an attribute, so the payload stays inert text.
    """
    hostile = allow(ImageRequest(slot="divider", prompt="x",
                                 alt='" onerror="alert(1)'), url='"><script>')
    markup = hostile.markup()

    assert "<script>" not in markup
    # Two quotes per attribute and no others: src, alt, loading, decoding,
    # data-provenance. Any extra one is a value that closed its own attribute.
    attributes = ("src", "alt", "loading", "decoding", "data-provenance")
    assert markup.count('"') == 2 * len(attributes), markup
    assert "&quot;" in markup and "&lt;" in markup and "&gt;" in markup


# ============================================ the plan comes first

def test_a_plan_names_the_photographs_the_customer_must_send() -> None:
    """A task for them, produced before anything is generated or charged."""
    result = plan((_request("premises"), _request("team"),
                   _request("header_texture")), resolve_url=_url)
    assert result.needs_photograph == ("premises", "team")
    assert [i.slot for i in result.allowed] == ["header_texture"]
    assert len(result.refused) == 2


def test_an_unknown_cost_is_unknown_and_never_zero() -> None:
    result = plan((_request("divider"),), resolve_url=_url)
    assert result.cost is None
    assert result.summary()["cost_state"] == "UNKNOWN"


def test_a_reported_cost_is_summed_only_over_what_reported_one() -> None:
    result = plan((_request("divider", cost=0.02),
                   _request("header_texture")), resolve_url=_url)
    assert result.cost == 0.02
    assert result.summary()["cost_state"] == "MEASURED"


def test_allow_raises_where_check_refuses() -> None:
    with pytest.raises(ImageryRefused, match="false statement"):
        allow(_request("team"), url="/img/t.webp")


# ============================================ placement

def test_only_decorative_images_are_placed_automatically() -> None:
    """Where a premises photograph belongs is a decision about the business. A
    template that drops one into a header has decided something nobody asked."""
    files = {"index.html": "<header><h1>X</h1></header><footer>f</footer>"}
    supplied = allow(_request("premises", Origin.SUPPLIED, supplied_by="Ayoub"),
                     url="/img/p.jpg")
    decorative = allow(_request("header_texture"), url="/img/h.webp")

    result = apply(files, (supplied, decorative))
    assert "/img/h.webp" in result["index.html"]
    assert "/img/p.jpg" not in result["index.html"]


def test_placement_holds_no_documentary_slot() -> None:
    assert all(not documentary(slot) for slot in PLACEMENT), (
        "a documentary slot with an automatic position is one the template "
        "will fill without being asked")


def test_applying_nothing_changes_nothing() -> None:
    files = {"index.html": "<header>x</header><footer>f</footer>"}
    assert apply(files, ()) == files


def test_placement_leaves_non_html_files_alone() -> None:
    files = {"index.html": "<header>x</header><footer>f</footer>",
             "sitemap.xml": "<urlset/>"}
    image = allow(_request("header_texture"), url="/i.webp")
    assert apply(files, (image,))["sitemap.xml"] == "<urlset/>"


def test_the_summary_states_the_rule_it_enforces() -> None:
    """A reader of the report should not have to infer it from the refusals."""
    note = plan((), resolve_url=_url).summary()["note"]
    assert "only photographs the business supplied" in note
