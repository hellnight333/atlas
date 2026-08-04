"""One customer entity, one immutable id, for the life of Atlas (M014).

A standing architectural rule, enforced here rather than trusted to memory:

    Business IDs are immutable. Every factory — website, Amazon, media, SaaS,
    support, billing — references the same Business id. No factory creates its
    own customer entity.

The failure this prevents is slow and quiet. A future factory needs to store
something about a company, finds it inconvenient to reach across to
``atlas_businesses``, and adds ``atlas_clients``. Nothing breaks that day.
Months later there are three rows for one company, the timeline is split three
ways, a suppression on one does not protect the others, and merging them is a
data-migration project rather than a decision.

So this test reads the source. It is the same shape as the guard on
``dependency.py``, which fails if executable code names a domain term, and the
one on Zustand selectors: a rule a person has to remember is a rule that gets
broken by someone who was not in the conversation.

The last class is the part that makes the rest trustworthy — it proves the
detectors actually fire on a violation, so a guard that quietly stopped
inspecting anything cannot pass by finding nothing.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from atlas_kernel.opportunity.models import Business

KERNEL = Path(__file__).resolve().parents[1] / "atlas_kernel"
DB_MODULE = KERNEL / "db.py"

#: Words that name "a company Atlas does business with".
#:
#: Matched as the **head noun**, not anywhere in the name. A thing is named by
#: what it ends in: ``WebsiteClient`` is a client, ``ClientSecrets`` is a set of
#: secrets, and ``ContactHistory`` is a history. Substring matching flagged both
#: of the latter on the first run — and a guard that cries wolf gets an
#: allow-list, then a longer allow-list, then ignored.
CUSTOMER_WORDS = (
    "customer",
    "client",
    "prospect",
    "lead",
    "seller",
    "buyer",
    "vendor",
    "merchant",
    "contact",
    "account",
    "company",
    # The canonical one. Included deliberately so the allow-lists below are
    # live: a future ``atlas_amazon_businesses`` or ``WebsiteBusiness`` is
    # caught by the same rule that permits the one real record. Leaving it out
    # made every entry below dead code, which is a guard that looks stricter
    # than it is.
    "business",
)

#: Deliberate exceptions, each with a reason. Anything added here should be
#: justified in the comment, not just silenced.
ALLOWED_TABLES = {
    # The one customer record. Nothing else belongs here.
    "atlas_businesses",
}

ALLOWED_MODELS = {
    # The one customer record. Nothing else belongs here.
    "Business",
}

_CREATE_TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", re.IGNORECASE)


def _declared_tables() -> list[str]:
    return _CREATE_TABLE.findall(DB_MODULE.read_text())


def _model_classes() -> list[tuple[str, Path]]:
    """Every class defined under the kernel, with the file it lives in.

    Parsed rather than grepped so a class name inside a docstring or a comment —
    such as the ones in this file — cannot trip the guard.
    """
    found: list[tuple[str, Path]] = []
    for path in KERNEL.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - would fail elsewhere first
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                found.append((node.name, path))
    return found


def _head_noun(name: str) -> str:
    """The last word of a class or table name.

    ``WebsiteClient`` -> ``client``. ``atlas_amazon_sellers`` -> ``sellers``.
    Handles both CamelCase and snake_case because the two conventions meet in
    this codebase — classes in Python, tables in SQL.
    """
    if "_" in name:
        return name.rsplit("_", 1)[-1].lower()
    words = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+", name)
    return (words[-1] if words else name).lower()


def _looks_like_a_customer(name: str) -> bool:
    """True when the name's head noun is a word for "a company we sell to"."""
    head = _head_noun(name)
    return any(head in {word, f"{word}s", f"{word}es"} for word in CUSTOMER_WORDS)


class TestNoSecondCustomerEntity:
    def test_no_other_table_stores_companies(self) -> None:
        offenders = [
            table
            for table in _declared_tables()
            if table not in ALLOWED_TABLES and _looks_like_a_customer(table)
        ]
        assert not offenders, (
            f"these tables look like a second customer record: {offenders}. "
            "Every factory references atlas_businesses.id — add your own table "
            "keyed on business_id instead, or justify an entry in ALLOWED_TABLES."
        )

    def test_no_other_model_represents_a_company(self) -> None:
        offenders = [
            f"{name} ({path.relative_to(KERNEL)})"
            for name, path in _model_classes()
            if name not in ALLOWED_MODELS and _looks_like_a_customer(name)
        ]
        assert not offenders, (
            f"these classes look like a second customer entity: {offenders}. "
            "Reference Business instead."
        )

    def test_exactly_one_customer_table_exists(self) -> None:
        """Stated positively, so deleting the guard's subject is also a failure."""
        assert "atlas_businesses" in _declared_tables()


class TestBusinessIdsAreImmutable:
    def test_the_id_cannot_be_reassigned(self) -> None:
        business = Business(name="Al Noor Clinic", geography="Dubai")
        with pytest.raises(ValueError):
            business.id = "something-else"  # type: ignore[misc]

    def test_merging_preserves_the_id(self) -> None:
        """The id is what every timeline entry and every future factory points
        at. A merge that changed it would orphan the history."""
        original = Business(name="Al Noor Clinic", geography="Dubai", website="https://alnoor.ae")
        merged = original.merged_with(
            Business(name="Al Noor Clinic LLC", geography="Dubai", phone="+97141234567")
        )
        assert merged.id == original.id

    def test_a_merge_that_changed_the_id_is_refused(self) -> None:
        """Belt and braces: ``model_copy`` does not validate, so the check is
        explicit rather than inherited from the model being frozen."""

        class SneakyBusiness(Business):
            def merged_with(self, other: Business) -> Business:  # type: ignore[override]
                merged = super().merged_with(other)
                return merged

        business = SneakyBusiness(name="Al Noor", geography="Dubai")
        assert business.merged_with(Business(name="Al Noor", geography="Dubai")).id == business.id


class TestTheGuardActuallyFires:
    """Proves the detectors are looking at something.

    Without this, a guard whose parsing silently broke would pass by finding no
    violations, which is indistinguishable from a clean codebase and much worse.
    """

    def test_it_would_catch_a_new_customer_table(self) -> None:
        assert _looks_like_a_customer("atlas_clients")
        assert _looks_like_a_customer("atlas_website_customers")
        assert _looks_like_a_customer("atlas_amazon_sellers")

    def test_it_would_catch_a_new_customer_model(self) -> None:
        assert _looks_like_a_customer("WebsiteClient")
        assert _looks_like_a_customer("BillingAccount")

    def test_it_does_not_fire_on_unrelated_names(self) -> None:
        for name in ("atlas_jobs", "atlas_renditions", "SceneRender", "OutreachMessage"):
            assert not _looks_like_a_customer(name), name

    def test_it_does_not_fire_on_names_that_merely_contain_the_word(self) -> None:
        """Both of these tripped a substring match on the first run. Neither is
        a customer entity: one is a set of OAuth secrets, the other is a record
        of when we last emailed someone."""
        for name in ("ClientSecrets", "ContactHistory", "AccountingPeriod"):
            assert not _looks_like_a_customer(name), name

    def test_the_allow_lists_are_load_bearing(self) -> None:
        """The canonical record is caught by the same rule that permits it.

        Without this the allow-lists would be dead code — every entry unmatched,
        the guard permitting things it was never flagging, and nobody the wiser
        until a real violation slipped through under the same blind spot.
        """
        assert _looks_like_a_customer("atlas_businesses")
        assert _looks_like_a_customer("Business")
        assert "atlas_businesses" in ALLOWED_TABLES
        assert "Business" in ALLOWED_MODELS

    def test_it_would_catch_a_factory_specific_business_table(self) -> None:
        assert _looks_like_a_customer("atlas_amazon_businesses")
        assert _looks_like_a_customer("WebsiteBusiness")

    def test_the_head_noun_is_what_decides(self) -> None:
        assert _head_noun("WebsiteClient") == "client"
        assert _head_noun("ClientSecrets") == "secrets"
        assert _head_noun("atlas_amazon_sellers") == "sellers"
        assert _head_noun("Business") == "business"

    def test_the_source_scan_finds_real_declarations(self) -> None:
        tables = _declared_tables()
        assert "atlas_businesses" in tables
        assert len(tables) > 20, "the table scan stopped finding declarations"

    def test_the_class_scan_finds_real_classes(self) -> None:
        names = {name for name, _ in _model_classes()}
        assert {"Business", "BusinessEvent", "Finding"} <= names

    def test_class_names_in_prose_do_not_trip_the_guard(self) -> None:
        """This very file names ``atlas_clients`` in a docstring. Parsing rather
        than grepping is what keeps that from being a violation."""
        names = {name for name, _ in _model_classes()}
        assert "WebsiteClient" not in names
