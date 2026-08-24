"""The Arabic capability, tested on the thing it must never do.

`arabic` is the opportunity this engine raises most often for UAE businesses and
the highest-value offer it makes. The obvious implementation calls a translation
model. That implementation publishes a claim about a business, in their name, in
a language the person approving it very often cannot read — and the failure is
silent, looks finished, and is discovered by a customer's customer.

So most of this file asserts refusals: no machine translation, no English left
sitting inside an Arabic page, no page at all when there is nothing an Arabic
reader could read, and no unsigned translation.

The rest tests the half that *is* ours to build — `dir="rtl"`, `lang="ar"`, the
hreflang pair, numerals that stay left-to-right inside right-to-left text. That
is the part businesses most often get wrong, and an Arabic page served `ltr`
reads as broken to a native reader even when every word is correct.
"""

from __future__ import annotations

import pytest

from atlas_kernel.execution.capabilities import (
    EXECUTORS,
    NothingToTranslate,
    build_arabic_experience,
)
from atlas_kernel.website.arabic import (
    ArabicContent,
    NotTranslated,
    check,
    is_arabic,
    pair,
    rtl,
    translated,
)
from atlas_kernel.website.content import (
    ContactDetails,
    Fact,
    FactSource,
    Prose,
    Service,
    SiteContent,
)


def _f(value: str) -> Fact:
    return Fact(value=value, source=FactSource.OPERATOR)


@pytest.fixture
def english() -> SiteContent:
    return SiteContent(
        business_name=_f("Al Hamra"),
        tagline=_f("Air-conditioning and plumbing in Dubai"),
        about=Prose(text="We have looked after Dubai homes since 2011.",
                    written_by="operator"),
        services=[Service(name=_f("AC servicing")), Service(name=_f("Plumbing"))],
        contact=ContactDetails(phone=_f("+971 4 555 0100"),
                               email=_f("hello@alhamra.ae")),
        location=_f("Dubai"))


@pytest.fixture
def arabic() -> ArabicContent:
    return ArabicContent(
        business_name="الحمراء",
        tagline="تكييف وسباكة في دبي",
        about="نخدم منازل دبي منذ عام ٢٠١١.",
        services={"AC servicing": "صيانة التكييف"},
        supplied_by="Ayoub")


# ============================================ Qevik does not translate

def test_no_arabic_at_all_is_a_refusal_not_a_translation(english) -> None:
    """The one behaviour that would make this capability dangerous."""
    with pytest.raises(NothingToTranslate) as refused:
        build_arabic_experience(content=english)
    assert "does not translate" in str(refused.value)
    assert "cannot read" in str(refused.value)


def test_nothing_in_the_module_calls_a_model() -> None:
    """By construction, not by convention.

    A translation call added later would look like an improvement in review —
    the capability would start producing complete Arabic sites — and nobody
    reviewing the diff reads Arabic.
    """
    import ast
    from pathlib import Path

    from atlas_kernel.execution.capabilities import arabic as executor
    from atlas_kernel.website import arabic as module

    for target in (module, executor):
        tree = ast.parse(Path(target.__file__).read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
                names.update(a.name for a in node.names)
        forbidden = names & {"llm", "LLMProvider", "ModelRegistry", "complete",
                             "translate", "googletrans", "openai"}
        assert forbidden == set(), f"{target.__name__} reaches for {forbidden}"


def test_the_provenance_states_that_no_machine_translated_it(english, arabic
                                                              ) -> None:
    """The question an approver asks about an Arabic page, answered on the
    record rather than somewhere they must go looking."""
    _, provenance = build_arabic_experience(content=english, arabic=arabic)
    assert provenance["machine_translated"] is False
    assert provenance["arabic"]["machine_translated"] is False
    assert provenance["arabic"]["supplied_by"] == "Ayoub"


# ============================================ no English inside an Arabic page

def test_a_service_with_no_arabic_is_dropped_not_carried_over(english, arabic
                                                               ) -> None:
    """An Arabic page with English sections is the artefact that looks finished
    and is not — and it is the one a reviewer who reads only English approves."""
    files, provenance = build_arabic_experience(content=english, arabic=arabic)
    page = files["index-ar.html"]

    assert "صيانة التكييف" in page, "the translated service must appear"
    assert "Plumbing" not in page, "the untranslated one must not"
    assert provenance["arabic"]["services_without_arabic"] == ["Plumbing"]


def test_an_untranslated_tagline_is_dropped(english) -> None:
    supplied = ArabicContent(about="نخدم منازل دبي منذ عام ٢٠١١.",
                             tagline="Air-conditioning and plumbing in Dubai",
                             supplied_by="Ayoub")
    # It is reported as untranslated rather than silently used.
    assert "tagline" in check(supplied, english)["untranslated"]


def test_english_pasted_into_an_arabic_field_is_caught(english) -> None:
    """The most common way a half-built Arabic site passes review: somebody
    works down a form and fills the gaps with what is already there."""
    pretend = ArabicContent(tagline="Air-conditioning and plumbing in Dubai",
                            about="We have looked after Dubai homes since 2011.",
                            supplied_by="Ayoub")
    report = check(pretend, english)
    assert report["buildable"] is False
    assert "not Arabic script" in report["statement"]
    assert set(report["untranslated"]) == {"tagline", "about"}


def test_a_page_with_nothing_an_arabic_reader_could_read_is_refused(english
                                                                    ) -> None:
    """Translating only the service names produces a page of headings."""
    thin = ArabicContent(services={"AC servicing": "صيانة التكييف"},
                         supplied_by="Ayoub")
    report = check(thin, english)
    assert report["buildable"] is False
    assert "nothing on it that an Arabic reader could read" in report["statement"]


def test_an_unsigned_translation_is_refused(english, arabic) -> None:
    """A translation is somebody's word, and an unsigned one cannot be queried
    when it turns out to be wrong."""
    unsigned = arabic.model_copy(update={"supplied_by": ""})
    report = check(unsigned, english)
    assert report["buildable"] is False
    assert "unsigned translation" in report["statement"]

    with pytest.raises(NotTranslated):
        translated(unsigned, english)


def test_the_script_check_can_tell_the_difference() -> None:
    assert is_arabic("تكييف وسباكة") is True
    assert is_arabic("Air-conditioning") is False
    assert is_arabic("") is False
    assert is_arabic("+971 4 555 0100") is False, "digits are not a translation"
    # Majority, not any: real Arabic copy contains Latin brand names and numerals.
    assert is_arabic("شركة Al Hamra للتكييف") is True


# ============================================ the half that is engineering

def test_an_arabic_page_is_right_to_left(english, arabic) -> None:
    """An Arabic page served `ltr` reads as broken to a native reader even when
    every word is correct."""
    files, _ = build_arabic_experience(content=english, arabic=arabic)
    page = files["index-ar.html"]
    assert 'lang="ar"' in page and 'dir="rtl"' in page
    assert "direction:rtl" in page


def test_phone_numbers_stay_left_to_right_inside_right_to_left_text(english,
                                                                    arabic) -> None:
    """Without this a phone number renders reversed, which is the single most
    visible defect on a badly built Arabic page."""
    files, _ = build_arabic_experience(content=english, arabic=arabic)
    page = files["index-ar.html"]
    assert 'a[href^="tel:"]' in page and "direction:ltr" in page


def test_the_two_languages_point_at_each_other(english, arabic) -> None:
    files, _ = build_arabic_experience(content=english, arabic=arabic)
    assert 'hreflang="ar"' in files["index-ar.html"]
    assert 'hreflang="en"' in files["index-ar.html"]
    assert 'href="index-ar.html"' in files["index.html"], "a language switch"
    assert 'href="index.html"' in files["index-ar.html"]


def test_a_dangling_alternate_is_never_emitted() -> None:
    """An alternate pointing at a page that does not exist tells a search engine
    a translation exists where it does not — worse than emitting none."""
    alone = rtl("<html lang=\"en\"><head><style>x</style></head></html>")
    assert "hreflang" not in alone


def test_one_sitemap_and_one_robots_for_two_languages(english, arabic) -> None:
    """Two sitemaps would compete for the same canonical."""
    files, _ = build_arabic_experience(content=english, arabic=arabic)
    assert sorted(f for f in files if not f.endswith(".html")) == [
        "robots.txt", "sitemap.xml"]


def test_facts_that_are_not_language_are_carried_across(english, arabic) -> None:
    """A phone number is the same phone number."""
    files, _ = build_arabic_experience(content=english, arabic=arabic)
    page = files["index-ar.html"]
    assert "+971 4 555 0100" in page
    assert "hello@alhamra.ae" in page


def test_the_business_name_falls_back_rather_than_leaving_no_name(english
                                                                  ) -> None:
    """The one field that falls back, because a page with no name is not a page
    — and a business name is often legitimately identical in both scripts."""
    unnamed = ArabicContent(tagline="تكييف وسباكة في دبي",
                            about="نخدم منازل دبي منذ عام ٢٠١١.",
                            supplied_by="Ayoub")
    result = translated(unnamed, english)
    assert result.business_name.value == "Al Hamra"


def test_the_arabic_content_is_attributed_to_the_person_not_to_qevik(english,
                                                                     arabic
                                                                     ) -> None:
    result = translated(arabic, english)
    assert result.tagline is not None
    assert result.tagline.source is FactSource.CUSTOMER
    assert "Ayoub" in result.tagline.note


# ============================================ the offer can now be performed

def test_the_offer_has_an_executor() -> None:
    """It did not, so the roadmap proposed work Qevik could not do — and it is
    the highest-value offer the engine makes."""
    assert "offer-arabic-experience" in EXECUTORS
    assert EXECUTORS["offer-arabic-experience"] is build_arabic_experience


def test_the_refusal_names_what_the_customer_must_supply(english) -> None:
    """A task for them, not a smaller job for us."""
    partial = ArabicContent(tagline="تكييف وسباكة في دبي", supplied_by="Ayoub")
    report = check(partial, english)
    assert report["buildable"] is True
    assert report["missing_services"] == ["AC servicing", "Plumbing"]


def test_generation_stays_deterministic(english, arabic) -> None:
    first, _ = build_arabic_experience(content=english, arabic=arabic)
    second, _ = build_arabic_experience(content=english, arabic=arabic)
    assert first == second


def test_the_bundle_still_passes_our_own_seo_audit(english, arabic) -> None:
    """Adding a language must not add a defect we sell the repair for."""
    from atlas_kernel.website import seo

    files, _ = build_arabic_experience(content=english, arabic=arabic)
    findings = seo.audit(files)["findings"]
    assert findings == [], findings


def test_pairing_leaves_the_english_bundle_otherwise_untouched(english, arabic
                                                               ) -> None:
    from atlas_kernel.website.generation import generate

    plain, _ = generate(english)
    merged = pair(plain, generate(translated(arabic, english))[0])
    # Only the language switch is added to the English page.
    assert merged["sitemap.xml"] == plain["sitemap.xml"]
    assert merged["robots.txt"] == plain["robots.txt"]


# ============================================ the registry's real contract

def test_every_executor_accepts_what_the_service_actually_passes() -> None:
    """Registering an executor with a different signature fails *at execution*.

    Both new capabilities did exactly that: the roadmap offered the work, the
    approval was granted, the job started, and `execute()` raised a TypeError
    inside a try/except that records failures as data — so the customer saw a
    task that produced nothing and no error anywhere named the cause.

    `Executor` is `Callable[..., ...]`, which cannot catch this. This can.
    """
    import inspect

    from atlas_kernel.execution.capabilities import CALLING_CONVENTION

    for offer, executor in sorted(EXECUTORS.items()):
        parameters = inspect.signature(executor).parameters
        takes_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD
                           for p in parameters.values())
        for name in CALLING_CONVENTION:
            assert name in parameters or takes_kwargs, (
                f"{offer} -> {executor.__name__} cannot accept {name!r}, which "
                "the execution service passes every executor")


def test_the_convention_matches_what_the_service_really_does() -> None:
    """Two lists that must agree, so one derives from the other by inspection
    rather than by somebody remembering."""
    import ast
    import inspect
    from pathlib import Path

    from atlas_kernel.execution import service
    from atlas_kernel.execution.capabilities import CALLING_CONVENTION

    tree = ast.parse(Path(inspect.getfile(service)).read_text(encoding="utf-8"))
    passed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "executor":
            passed = {kw.arg for kw in node.keywords if kw.arg}
    assert passed == set(CALLING_CONVENTION), (
        f"the service passes {passed}, the convention says "
        f"{set(CALLING_CONVENTION)}")
