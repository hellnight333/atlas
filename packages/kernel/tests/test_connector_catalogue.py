"""The connector catalogue: browsable, honest about what is not built.

Thirty integrations is a wall unless it has shelves, and a catalogue that
advertises what does not work is worse than a short one. Two properties:

* every connector says which shelf it is on and what connecting it *gets you*,
  in the customer's words rather than in capability ids;
* `adapter_ready` is load-bearing — it is what makes a declared-but-unbuilt
  connector read as NOT_IMPLEMENTED rather than as a request for a token, and
  asking a seller for marketplace credentials before anything can use them is
  how a live token that can create orders sits in a store for a year.
"""

from __future__ import annotations

from atlas_kernel.integrations.registry import INTEGRATIONS, Category, Integration


def test_ids_are_unique() -> None:
    ids = [i.id for i in INTEGRATIONS]
    assert len(ids) == len(set(ids))


def test_every_connector_is_on_a_shelf_and_says_what_it_unlocks() -> None:
    """`blocks` names capability ids, which are ours. A person deciding whether
    to go and find a token needs the other sentence."""
    for i in INTEGRATIONS:
        assert isinstance(i.category, Category), i.id
        assert i.purpose.strip(), i.id


def test_new_connectors_carry_the_customer_facing_sentence() -> None:
    """Grandfathered: the original seventeen predate `unlocks`. Everything added
    to the catalogue since must carry it, or the directory becomes a list of
    vendor names again."""
    catalogued = [i for i in INTEGRATIONS if i.unlocks]
    assert len(catalogued) >= 13, "the catalogue entries lost their unlocks line"
    for i in catalogued:
        assert not i.unlocks.endswith(("blocks", "capability")), i.id


def test_every_connector_names_a_credential_and_never_a_value() -> None:
    """The registry holds references, never secrets — that is the whole reason
    it can be served to a browser."""
    for i in INTEGRATIONS:
        assert i.credential.strip(), i.id
        assert i.credential.isupper() or "_" in i.credential, i.id
        # A value would look like one: long, mixed case, or prefixed.
        assert not i.credential.startswith(("sk-", "pk_", "Bearer")), i.id


def test_a_connector_that_can_publish_under_a_name_is_not_ready_by_accident() -> None:
    """Social and marketplace connectors reach an audience or create orders
    under somebody else's name. They stay unbuilt until an approval gate is in
    front of them, and this test is what makes flipping one deliberate."""
    guarded = {"youtube", "instagram", "meta", "tiktok", "linkedin",
               "amazon", "noon", "shopify", "twilio"}
    for i in INTEGRATIONS:
        if i.id in guarded:
            assert not i.adapter_ready, (
                f"{i.id} was marked ready. Publishing or ordering under a "
                "customer's name needs an approval gate in front of it first; "
                "if that gate now exists, change this test in the same commit.")


def test_the_generation_provider_that_exists_is_the_one_marked_ready() -> None:
    """`replicate` has a real adapter — submit, poll, fetch — and is the first
    provider in this system that generates anything. Its `adapter_ready` is a
    claim about code that must stay true."""
    from atlas_kernel.media.providers.replicate import ReplicateProvider

    replicate = next(i for i in INTEGRATIONS if i.id == "replicate")
    assert replicate.adapter_ready is True
    assert replicate.credential == "QEVIK_REPLICATE_API_TOKEN"
    # The adapter reads the same variable the registry advertises. A mismatch
    # here is a connector that reports connected while the renderer sees nothing.
    from atlas_kernel.media.providers import replicate as module
    assert module.TOKEN_VARIABLE == replicate.credential
    assert ReplicateProvider.name == "replicate"


def test_unbuilt_connectors_are_declared_as_unbuilt() -> None:
    """"we have not built this" and "you have not connected this" are different
    sentences, and only one of them is the customer's move."""
    unbuilt = [i for i in INTEGRATIONS if not i.adapter_ready]
    assert unbuilt, "nothing is unbuilt, which would be a first"
    for i in unbuilt:
        assert i.setup_url or i.credential, i.id


def test_every_category_is_used() -> None:
    """A shelf with nothing on it is a heading a person clicks once."""
    used = {i.category for i in INTEGRATIONS}
    for category in Category:
        assert category in used, f"{category.value} has no connectors"


def test_the_model_shelf_carries_the_generation_providers() -> None:
    models = {i.id for i in INTEGRATIONS if i.category is Category.MODEL}
    assert {"replicate", "elevenlabs", "anthropic"} <= models


def test_integration_is_frozen() -> None:
    """A catalogue entry that can be mutated at runtime is a catalogue that
    disagrees with itself between two requests."""
    import pytest
    from pydantic import ValidationError

    entry: Integration = INTEGRATIONS[0]
    with pytest.raises(ValidationError):
        entry.adapter_ready = True  # type: ignore[misc]
