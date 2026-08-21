"""One message, one business — enforced rather than hoped for.

Written after a real failure. A staffing agency's draft carried its correct
name, its correct number and its correct confirmed weakness, and then offered
the real-estate sample described as "a property company". Nothing was
fabricated and nothing belonged to another prospect; the message was simply
about two businesses at once, because demo choice lived in three dicts keyed on
the same category and they had drifted apart.

So these tests do not check that fields are individually right. They check that
the finished message is internally consistent, and that three deliberately
different prospects cannot borrow each other's anything.
"""

from __future__ import annotations

import pytest

from atlas_kernel.outreach import consistency, demos, scoring

# --- three prospects that share nothing -------------------------------------

PROSPECTS = {
    "staffing": {
        "id": "aaaaaaaa-0000-0000-0000-000000000001",
        "name": "360 Agency", "category": "professional",
        "phone": "058 550 0125", "host": "360agency.me",
    },
    "restaurant": {
        "id": "bbbbbbbb-0000-0000-0000-000000000002",
        "name": "Flaky Pastry Croissant", "category": "food",
        "phone": "054 998 4434", "host": "flakypastry.ae",
    },
    "automotive": {
        "id": "cccccccc-0000-0000-0000-000000000003",
        "name": "RnB Car Care Professionals", "category": "automotive",
        "phone": "056 441 2345", "host": "rnbcarcare.com",
    },
}


def others_except(key: str) -> tuple[consistency.Other, ...]:
    return tuple(
        consistency.Other(business_id=p["id"], name=p["name"], phone=p["phone"],
                          host=p["host"], demo_url="")
        for k, p in PROSPECTS.items() if k != key
    )


def score_for(key: str, speakable=("arabic", "click_to_call")) -> scoring.Score:
    p = PROSPECTS[key]
    return scoring.score(
        business_id=p["id"], name=p["name"], website=f"https://{p['host']}/",
        phone=p["phone"], email="", category=p["category"], audit_count=1,
        audit={"http_status": 200, "load_ms": 1200, "observations":
               [{"feature": f, "status": "not_found"} for f in speakable]
               + [{"feature": "booking_link", "status": "not_found"},
                  {"feature": "insurance_info", "status": "unverified"}]},
    )


def selection_for(key: str) -> demos.Selection:
    p = PROSPECTS[key]
    return demos.select(p["category"], weaknesses=("arabic", "click_to_call"))


def message_for(key: str) -> str:
    """A message shaped exactly like the generator's, from this prospect only."""
    p, chosen = PROSPECTS[key], selection_for(key)
    return "\n\n".join([
        f"Hello — I'm Ayoub. I build websites for businesses in Dubai, and I'm writing "
        f"about {p['name']}.",
        "On a phone, your number isn't tappable — you have to copy it out by hand to call.",
        f"Here's one of our own samples — {chosen.demo.name}, a {chosen.demo.trade} site. "
        f"It's ours, not a client's:",
        chosen.url,
        "Ayoub Soleimani\nQevik\n+971 50 102 9104",
    ])


def verdict(key: str, text: str | None = None) -> list[str]:
    p, score = PROSPECTS[key], score_for(key)
    return consistency.check(
        text if text is not None else message_for(key),
        business_id=p["id"], speakable=score.speakable, unfixable=score.unfixable,
        unverified=score.unverified, chosen=selection_for(key),
        category=p["category"], others=others_except(key),
    )


# --- each prospect gets its own everything ----------------------------------

@pytest.mark.parametrize("key", list(PROSPECTS))
def test_a_generated_message_is_internally_consistent(key) -> None:
    assert verdict(key) == [], verdict(key)


@pytest.mark.parametrize("key", list(PROSPECTS))
def test_a_message_carries_no_other_prospects_details(key) -> None:
    text = message_for(key).lower()
    for other, p in PROSPECTS.items():
        if other == key:
            continue
        assert p["name"].lower() not in text, f"{key} carries {other}'s name"
        assert p["phone"].lower() not in text, f"{key} carries {other}'s phone"
        assert p["host"].lower() not in text, f"{key} carries {other}'s website"


def test_three_prospects_select_three_different_demos() -> None:
    chosen = {k: selection_for(k).demo.slug for k in PROSPECTS}
    assert len(set(chosen.values())) == 3, chosen
    assert chosen["staffing"] == "sample-ledgerloop"
    assert chosen["restaurant"] == "sample-nar"
    assert chosen["automotive"] == "sample-apex"


def test_the_real_case_that_failed() -> None:
    """360 Agency must not be told about a property company."""
    text = message_for("staffing").lower()
    assert "sample-meridian" not in text
    assert "property company" not in text
    assert "estate agency" not in text
    assert "sample-ledgerloop" in text
    assert selection_for("staffing").demo.slug != "sample-meridian"


def test_meridian_is_only_ever_offered_to_property_businesses() -> None:
    meridian = demos.BY_SLUG["sample-meridian"]
    assert meridian.serves == frozenset({"real_estate", "property"})
    for category in ("professional", "food", "automotive", "beauty", "home",
                     "retail", "health", "dental", ""):
        chosen = demos.select(category)
        assert chosen.demo is None or chosen.demo.slug != "sample-meridian", category


# --- the guard has to be able to fail ---------------------------------------

def test_it_catches_a_demo_from_the_wrong_trade() -> None:
    """The exact failure: the real-estate sample offered to a staffing agency."""
    wrong = ("Hello — I'm Ayoub, writing about 360 Agency.\n\n"
             "Here's something we built for a property company — it's our own sample:\n"
             "https://sites.qevik.ai/sample-meridian/")
    problems = verdict("staffing", wrong)
    assert problems, "a property-company message passed for a staffing agency"
    assert any("not the selected demo" in p for p in problems), problems


def test_it_catches_a_url_that_is_not_the_selected_demo() -> None:
    text = message_for("restaurant").replace("sample-nar", "sample-verdant")
    problems = verdict("restaurant", text)
    assert any("sample-verdant" in p for p in problems), problems
    assert any("does not carry the selected demo URL" in p for p in problems), problems


def test_it_catches_another_prospects_name() -> None:
    text = message_for("staffing") + "\n\nP.S. also relevant to RnB Car Care Professionals."
    assert any("another prospect's name" in p for p in verdict("staffing", text))


def test_it_catches_another_prospects_phone_number() -> None:
    text = message_for("staffing") + "\n\nCall 054 998 4434."
    assert any("another prospect's phone" in p for p in verdict("staffing", text))


def test_it_catches_another_prospects_website() -> None:
    text = message_for("staffing") + "\n\nLike flakypastry.ae does."
    assert any("another prospect's website" in p for p in verdict("staffing", text))


def test_it_catches_a_sample_described_as_built_for_them() -> None:
    text = message_for("staffing").replace("Here's one of our own samples —",
                                           "So I built you a working example —")
    assert any("built for this prospect" in p for p in verdict("staffing", text))


def test_it_catches_the_wrong_trade_noun_even_with_the_right_url() -> None:
    """Right link, wrong description — the half of the bug a URL check misses."""
    text = message_for("staffing").replace("a B2B software site", "a estate agency site")
    assert any("estate agency site" in p for p in verdict("staffing", text)), verdict("staffing", text)


def test_it_catches_an_unfixable_claim() -> None:
    text = message_for("staffing") + "\n\nWe can add online booking too."
    problems = verdict("staffing", text)
    assert any("booking" in p for p in problems), problems


def test_it_catches_a_not_verified_claim() -> None:
    text = message_for("staffing") + "\n\nYou have no insurance information either."
    assert any("NOT_VERIFIED" in p for p in verdict("staffing", text))


def test_it_catches_a_price_in_a_first_message() -> None:
    text = message_for("staffing") + "\n\nIt's AED 1,500 to set up."
    assert any("price" in p for p in verdict("staffing", text))


def test_it_catches_qevik_presented_as_a_company() -> None:
    text = message_for("staffing").replace("Qevik\n", "Qevik FZ-LLC\n")
    assert any("own company" in p for p in verdict("staffing", text))


def test_it_catches_a_demo_link_where_none_was_selected() -> None:
    """No sample serves this trade, so no sample may be linked."""
    none = demos.select("places")
    assert none.demo is None and not none.matched
    problems = consistency.check(
        "Hello.\n\nhttps://sites.qevik.ai/sample-nar/",
        business_id="x", speakable=(), unfixable=(), unverified=(),
        chosen=none, category="places", others=(),
    )
    assert any("none was selected" in p for p in problems), problems


def test_the_checker_passes_a_genuinely_clean_message() -> None:
    """A check that rejects everything is not a check."""
    for key in PROSPECTS:
        assert verdict(key) == []


# --- the registry is the only source ----------------------------------------

def test_demo_wording_and_url_come_from_the_same_object() -> None:
    for demo in demos.DEMOS:
        chosen = demos.Selection(demo=demo, matched=True)
        assert chosen.url.endswith(f"/{demo.slug}/")
        assert demo.trade and not demo.trade.startswith(("a ", "an ")), demo.slug


def test_no_module_keeps_its_own_category_to_sample_map() -> None:
    """Three of these existed and disagreed. There is now one."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for path in ((root / "infra" / "score_prospects.py"),
                 (root / "infra" / "first_five.py"),
                 (root / "packages/kernel/atlas_kernel/control/sales.py")):
        source = path.read_text(encoding="utf-8")
        assert "SAMPLE_FOR" not in source, f"{path.name} still keeps its own demo map"
        assert "TRADE = {" not in source, f"{path.name} still keeps its own trade map"


# --- the headline and the message must open with the same thing -------------

def test_the_angle_a_page_headlines_is_the_one_its_message_uses() -> None:
    """A page that headlines one gap while its message opens with another leaves
    the operator deciding which to trust."""
    for key, p in PROSPECTS.items():
        score = score_for(key)
        chosen = selection_for(key)
        leads = demos.leadable(chosen, score.speakable)
        assert leads, key
        # The generator drops the same feature for the same reason.
        if chosen.url and not chosen.bilingual:
            assert "arabic" not in leads, key
        else:
            assert leads == score.speakable, key


def test_arabic_is_only_led_with_when_the_link_has_arabic() -> None:
    english_only = demos.select("food", weaknesses=("arabic", "click_to_call"))
    assert english_only.bilingual is False
    assert "arabic" not in demos.leadable(english_only, ("arabic", "click_to_call"))

    bilingual = demos.select("dental", weaknesses=("arabic",))
    assert bilingual.bilingual is True
    assert "arabic" in demos.leadable(bilingual, ("arabic",))

    theirs = demos.select("dental", prospect_demo_url="https://sites.qevik.ai/demo-x/")
    assert theirs.bilingual is True
    assert "arabic" in demos.leadable(theirs, ("arabic",))


def test_a_prospect_with_no_matched_demo_may_still_lead_with_anything() -> None:
    """Nothing is linked, so nothing constrains what may be raised."""
    none = demos.select("places", weaknesses=("arabic", "https"))
    assert none.url == ""
    assert demos.leadable(none, ("arabic", "https")) == ("arabic", "https")


def test_every_trade_noun_says_what_kind_of_thing_it_is() -> None:
    """A message says "one of our own samples — NAR, a restaurant site".

    The noun has to complete that sentence and say what the thing is. Some
    samples are websites and some are products; an editing slip once left
    LedgerLoop reading "a B2B software", and HIRE360 — a talent marketplace —
    was briefly described as a website.
    """
    endings = ("site", "app", "platform", "game", "concept")
    for demo in demos.DEMOS:
        assert demo.trade.endswith(endings), f"{demo.slug}: {demo.trade!r} names no product type"
        assert not demo.trade.startswith(("a ", "an ")), f"{demo.slug} carries its own article"
        assert demos.article(demo.trade) in ("a", "an")


def test_hire360_is_the_recruitment_demo_and_only_that() -> None:
    hire = demos.BY_SLUG["sample-hire360"]
    assert hire.serves == frozenset({"recruitment", "staffing", "hospitality"})
    assert hire.bilingual is True
    # It must not leak into neighbouring professional categories.
    for category in ("professional", "retail", "food", "automotive", "beauty",
                     "home", "health", "dental", ""):
        chosen = demos.select(category)
        assert chosen.demo is None or chosen.demo.slug != "sample-hire360", category
    # And a recruitment business must get it rather than the B2B SaaS sample.
    assert demos.select("recruitment").demo.slug == "sample-hire360"


def test_a_recruitment_message_never_mentions_the_saas_or_property_samples() -> None:
    chosen = demos.select("recruitment", weaknesses=("arabic",))
    text = (f"Here's one of our own samples — {chosen.demo.name}, "
            f"{demos.article(chosen.demo.trade)} {chosen.demo.trade}. "
            f"It's ours, not a client's:\n{chosen.url}")
    problems = consistency.check(
        text, business_id="x", speakable=("arabic",), unfixable=(), unverified=(),
        chosen=chosen, category="recruitment", others=(),
    )
    assert problems == [], problems
    for forbidden in ("ledgerloop", "meridian", "property", "estate agency", "B2B"):
        assert forbidden.lower() not in text.lower(), forbidden
