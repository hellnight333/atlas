"""The credential vault, tested on every way a secret escapes.

§17 lists fourteen. They are all here, and they are the point of the module —
storing a key is easy, and the whole value is in the places the value must never
turn up: an API response, an event, a report, an error, another tenant's
request, or a commit.

The one that needed the most care is the provider echo. A 400 quoting the
offending header is a normal API response and an abnormal thing to persist, so
verification redacts against the secret it just used rather than trusting the
provider's phrasing.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from atlas_kernel.credentials import (
    CredentialDisabled,
    CredentialMissing,
    CredentialService,
    LockedOut,
    MemorySecretStore,
    Status,
    Vault,
    VaultError,
    VaultLocked,
    VaultSealed,
    fingerprint,
    hint,
    to_event,
)
from atlas_kernel.credentials.service import STORED
from atlas_kernel.opportunity.tenancy import TenantRequired

A, B = "tenant-alpha", "tenant-beta"
SECRET = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.fixture
def vault() -> Vault:
    opened = Vault(MemorySecretStore(), master_key="a-master-key-from-the-env")
    opened.unlock()
    return opened


@pytest.fixture
def service(vault) -> CredentialService:
    return CredentialService(vault)


# ============================================ 1–6. the secret never comes out

def test_a_stored_credential_is_not_in_its_own_record(service) -> None:
    record = service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    assert SECRET not in repr(record.model_dump())
    assert SECRET not in repr(record.describe())


def test_the_centre_response_carries_no_secret(service) -> None:
    service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    assert SECRET not in repr(service.centre(tenant=A))


def test_a_timeline_event_carries_no_secret(service) -> None:
    record = service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    assert SECRET not in repr(to_event(record, STORED).detail)


def test_a_verification_detail_carries_no_secret(service) -> None:
    """Providers echo requests. A 400 quoting the header is normal for them and
    abnormal to store."""
    service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    result = service.verify(
        provider="ai-visibility", tenant=A,
        probe=lambda secret: (Status.INVALID_CREDENTIAL, f"rejected key {secret}"))

    assert SECRET not in result.detail
    assert "<redacted>" in result.detail
    assert result.status is Status.INVALID_CREDENTIAL


def test_a_vault_error_carries_no_secret(vault) -> None:
    vault.put("ref", SECRET)
    other = Vault(MemorySecretStore(), master_key="a-different-master-key")
    other.unlock()
    with pytest.raises(VaultError) as raised:
        other.get("ref")
    assert SECRET not in str(raised.value)


def test_the_hint_shows_four_characters_and_no_more() -> None:
    shown = hint(SECRET)
    assert shown == "…6789"
    assert len(shown.strip("…")) == 4
    assert SECRET[:-4] not in shown


def test_a_short_secret_gets_no_hint_at_all() -> None:
    """Four of eight characters is most of the key."""
    assert hint("abc123") == "…"


def test_a_fingerprint_identifies_without_revealing() -> None:
    assert fingerprint(SECRET) == fingerprint(SECRET)
    assert fingerprint(SECRET) != fingerprint(SECRET + "x")
    assert SECRET[:8] not in fingerprint(SECRET)


# ============================================ 7 & 14. tenancy

def test_another_tenant_cannot_read_a_credential(service) -> None:
    service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    with pytest.raises(CredentialMissing):
        service.resolve(provider="ai-visibility", tenant=B)
    assert service.record(provider="ai-visibility", tenant=B) is None


def test_a_missing_credential_never_falls_back_to_another_tenants(service) -> None:
    """The failure this prevents is one customer's work billed to another."""
    service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    assert service.status(provider="ai-visibility", tenant=B) is Status.NOT_CONFIGURED
    with pytest.raises(CredentialMissing):
        service.resolve(provider="ai-visibility", tenant=B)


def test_one_tenants_centre_shows_only_their_own(service) -> None:
    service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    for row in service.centre(tenant=B)["credentials"]:
        assert row["configured"] is False


def test_every_entry_point_requires_a_tenant(service) -> None:
    for call in (lambda: service.store(provider="p", tenant=None, secret="x"),
                 lambda: service.resolve(provider="p", tenant=None),
                 lambda: service.centre(tenant=None)):
        with pytest.raises(TenantRequired):
            call()


def test_the_vault_reference_is_tenant_scoped() -> None:
    from atlas_kernel.credentials import reference_for

    assert reference_for("qwen", A) != reference_for("qwen", B)
    assert A in reference_for("qwen", A)


# ============================================ 8. the lock

def test_repeated_bad_attempts_lock_the_vault() -> None:
    locked = Vault(MemorySecretStore(), master_key="m",
                   pin_hash=Vault.hash_pin("1234"))
    for _ in range(4):
        with pytest.raises(VaultLocked):
            locked.unlock("9999")
    with pytest.raises(LockedOut):
        locked.unlock("9999")
    # And the correct PIN does not bypass the lockout.
    with pytest.raises(LockedOut):
        locked.unlock("1234")


def test_a_failed_unlock_says_nothing_about_the_pin() -> None:
    locked = Vault(MemorySecretStore(), master_key="m",
                   pin_hash=Vault.hash_pin("1234"))
    with pytest.raises(VaultLocked) as raised:
        locked.unlock("9999")
    message = str(raised.value)
    assert "1234" not in message
    assert "length" not in message and "close" not in message


def test_a_locked_vault_yields_nothing() -> None:
    locked = Vault(MemorySecretStore(), master_key="m",
                   pin_hash=Vault.hash_pin("1234"))
    with pytest.raises(VaultLocked):
        locked.put("ref", SECRET)
    locked.unlock("1234")
    locked.put("ref", SECRET)
    locked.lock()
    with pytest.raises(VaultLocked):
        locked.get("ref")


def test_an_unlock_expires() -> None:
    brief = Vault(MemorySecretStore(), master_key="m",
                  pin_hash=Vault.hash_pin("1234"), ttl=timedelta(seconds=-1))
    brief.unlock("1234")
    assert not brief.unlocked


def test_the_pin_is_never_stored() -> None:
    stored = Vault.hash_pin("1234")
    assert "1234" not in stored
    assert Vault(MemorySecretStore(), master_key="m", pin_hash=stored)._pin_matches("1234")


def test_a_trivially_short_pin_is_refused() -> None:
    with pytest.raises(VaultError, match="at least four"):
        Vault.hash_pin("12")


# ============================================ sealed beats plaintext

def test_a_vault_with_no_master_key_refuses_rather_than_degrading() -> None:
    """A vault that falls back to plaintext under pressure protects nothing."""
    sealed = Vault(MemorySecretStore(), master_key="")
    assert sealed.sealed
    with pytest.raises(VaultSealed):
        sealed.unlock()
    with pytest.raises(VaultSealed):
        sealed.put("ref", SECRET)


def test_the_stored_form_is_not_the_secret(vault) -> None:
    store = MemorySecretStore()
    opened = Vault(store, master_key="m")
    opened.unlock()
    opened.put("ref", SECRET)
    assert SECRET not in store.get("ref")
    assert opened.get("ref") == SECRET


def test_the_same_secret_stored_twice_looks_different(vault) -> None:
    """Otherwise the store leaks which credentials match without decrypting."""
    vault.put("one", SECRET)
    vault.put("two", SECRET)
    store = vault._store
    assert store.get("one") != store.get("two")


def test_a_tampered_record_is_refused_not_decrypted(vault) -> None:
    vault.put("ref", SECRET)
    salt, cipher, tag = vault._store.get("ref").split(".")
    vault._store.put("ref", f"{salt}.{cipher}.{tag[:-4]}AAAA")
    with pytest.raises(VaultError, match="could not be verified"):
        vault.get("ref")


# ============================================ 9 & 10. disable and rotate

def test_a_disabled_credential_cannot_be_used(service) -> None:
    service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    service.set_enabled(provider="ai-visibility", tenant=A, enabled=False)

    assert service.status(provider="ai-visibility", tenant=A) is Status.DISABLED
    with pytest.raises(CredentialDisabled):
        service.resolve(provider="ai-visibility", tenant=A)


def test_disabling_does_not_destroy_the_credential(service) -> None:
    service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    service.set_enabled(provider="ai-visibility", tenant=A, enabled=False)
    service.set_enabled(provider="ai-visibility", tenant=A, enabled=True)
    assert service.resolve(provider="ai-visibility", tenant=A) == SECRET


def test_a_failed_rotation_preserves_the_working_credential(service) -> None:
    service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    with pytest.raises(VaultError):
        service.rotate(provider="ai-visibility", tenant=A, secret="   ")
    assert service.resolve(provider="ai-visibility", tenant=A) == SECRET


def test_a_rotation_clears_the_old_verification(service) -> None:
    """The old result was about the old key; carrying it forward would show an
    untested credential as CONNECTED."""
    service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    service.verify(provider="ai-visibility", tenant=A,
                   probe=lambda secret: (Status.CONNECTED, "ok"))
    assert service.status(provider="ai-visibility", tenant=A) is Status.CONNECTED

    service.rotate(provider="ai-visibility", tenant=A, secret="sk-new-key-value")
    assert service.status(provider="ai-visibility", tenant=A) is Status.PENDING_CREDENTIAL


# ============================================ storing is not connecting

def test_storing_a_key_does_not_claim_it_works(service) -> None:
    """Somebody typed a key. That is not evidence it is a working key."""
    record = service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    assert record.status is Status.PENDING_CREDENTIAL
    assert record.status is not Status.CONNECTED


def test_a_provider_error_is_recorded_as_such(service) -> None:
    service.store(provider="ai-visibility", tenant=A, secret=SECRET)

    def explodes(secret: str):
        raise ConnectionError("network down")

    result = service.verify(provider="ai-visibility", tenant=A, probe=explodes)
    assert result.status is Status.PROVIDER_ERROR
    assert result.detail == "ConnectionError"


def test_an_unconfigured_provider_still_appears_in_the_centre(service) -> None:
    """"You have not connected Stripe" is the row a person needs; an empty
    list does not say it."""
    listed = service.centre(tenant=A)
    providers = {row["provider"] for row in listed["credentials"]}
    assert "cloudflare" in providers
    row = next(r for r in listed["credentials"] if r["provider"] == "cloudflare")
    assert row["status"] == Status.NOT_CONFIGURED.value
    assert row["credential"], "it must name what to add"
    assert row["blocks"], "and what it holds up"


# ============================================ the join to what exists

def test_a_credential_produces_the_existing_connection_model(service) -> None:
    """No parallel credential model — publication and integrations are unchanged."""
    from atlas_kernel.publication.models import Connection

    service.store(provider="ai-visibility", tenant=A, secret=SECRET)
    connection = service.connection(provider="ai-visibility", tenant=A)

    assert isinstance(connection, Connection)
    assert connection.tenant_id == A
    assert connection.target == "ai-visibility"
    # The Connection carries a reference, never the value — its own guard.
    assert SECRET not in connection.reference


# ============================================ §8 model registry from the vault

def test_no_stored_credential_registers_no_model(service) -> None:
    """Registering a model that cannot run turns a clear refusal at selection
    time into a confusing provider error later, further from the cause."""
    from atlas_kernel.credentials.models import Role, Selection, chosen_for, registry_for

    registry = registry_for(service, tenant=A)
    assert registry.models == []
    _spec, why = chosen_for(registry, Selection(), Role.PLANNING)
    assert why == "no model is registered"


def test_a_stored_credential_registers_its_models(service) -> None:
    from atlas_kernel.credentials.models import registry_for

    service.store(provider="qwen", tenant=A, secret="sk-qwen-value-123")
    names = {m.name for m in registry_for(service, tenant=A).models}
    assert {"qwen-turbo", "qwen-plus", "qwen-max"} <= names


def test_a_disabled_provider_registers_nothing(service) -> None:
    from atlas_kernel.credentials.models import registry_for

    service.store(provider="qwen", tenant=A, secret="sk-qwen-value-123")
    service.set_enabled(provider="qwen", tenant=A, enabled=False)
    assert registry_for(service, tenant=A).models == []


def test_an_invalid_credential_registers_nothing(service) -> None:
    from atlas_kernel.credentials.models import registry_for

    service.store(provider="qwen", tenant=A, secret="sk-qwen-value-123")
    service.verify(provider="qwen", tenant=A,
                   probe=lambda secret: (Status.INVALID_CREDENTIAL, "rejected"))
    assert registry_for(service, tenant=A).models == []


def test_a_stored_but_untested_credential_is_usable(service) -> None:
    """Refusing it would mean a credential could only be proven by a test that
    needs it."""
    from atlas_kernel.credentials.models import registry_for

    service.store(provider="qwen", tenant=A, secret="sk-qwen-value-123")
    assert service.status(provider="qwen", tenant=A) is Status.PENDING_CREDENTIAL
    assert registry_for(service, tenant=A).models


def test_one_tenants_models_are_not_anothers(service) -> None:
    from atlas_kernel.credentials.models import registry_for

    service.store(provider="qwen", tenant=A, secret="sk-qwen-value-123")
    assert registry_for(service, tenant=A).models
    assert registry_for(service, tenant=B).models == []


def test_a_role_can_name_its_own_model_without_a_code_change(service) -> None:
    from atlas_kernel.credentials.models import Role, Selection, chosen_for, registry_for

    service.store(provider="qwen", tenant=A, secret="sk-qwen-value-123")
    registry = registry_for(service, tenant=A)
    selection = Selection(by_role={"implementation": "qwen-max",
                                   "review": "qwen-plus"})

    spec, why = chosen_for(registry, selection, Role.IMPLEMENTATION)
    assert spec.id == "qwen-max" and why == "selected"
    spec, why = chosen_for(registry, selection, Role.REVIEW)
    assert spec.id == "qwen-plus" and why == "selected"


def test_a_default_is_reported_as_a_default_not_a_decision(service) -> None:
    """A report must not present a fallback as something somebody chose."""
    from atlas_kernel.credentials.models import Role, Selection, chosen_for, registry_for

    service.store(provider="qwen", tenant=A, secret="sk-qwen-value-123")
    _spec, why = chosen_for(registry_for(service, tenant=A), Selection(),
                            Role.PLANNING)
    assert "defaulted" in why


def test_selecting_an_unavailable_model_says_so(service) -> None:
    from atlas_kernel.credentials.models import Role, Selection, chosen_for, registry_for

    service.store(provider="qwen", tenant=A, secret="sk-qwen-value-123")
    spec, why = chosen_for(registry_for(service, tenant=A),
                           Selection(by_role={"planning": "claude-opus-5"}),
                           Role.PLANNING)
    assert spec is None
    assert "not available" in why


def test_a_provider_with_no_adapter_is_not_asked_for_a_key() -> None:
    """"We have not built this" is our move, not the customer's."""
    from atlas_kernel.integrations import BY_ID, IntegrationStatus
    from atlas_kernel.publication import ConnectionStore

    store = ConnectionStore()
    for provider in ("deepseek", "stripe"):
        assert BY_ID[provider].status(store, tenant=A) is IntegrationStatus.NOT_IMPLEMENTED

    # `smtp` left this group at M1: the adapter exists, so the honest answer is
    # that the key is missing rather than that the feature is unbuilt. Asking
    # for a key we can use is fair; asking for one we cannot is not.
    assert BY_ID["smtp"].status(store, tenant=A) is IntegrationStatus.PENDING_CREDENTIAL


# ============================================ records outlive the process

def _service(events: list) -> CredentialService:
    from atlas_kernel.credentials.service import CredentialService
    from atlas_kernel.credentials.vault import MemorySecretStore, Vault

    return CredentialService(Vault(MemorySecretStore(), master_key="test-only"),
                             events=events, sink=events.append)


def test_a_saved_credential_is_still_saved_after_a_restart() -> None:
    """The bug this replaced: the vault persisted the secret and the *record*
    did not, so the Centre read back NOT_CONFIGURED with the key still in the
    vault — unreachable, and impossible to forget through the UI."""
    from atlas_kernel.credentials.service import Status

    events: list = []
    _service(events).store(provider="anthropic", tenant="t1", secret="k-not-real")
    after = _service(events)
    assert after.status(provider="anthropic",
                        tenant="t1") is Status.PENDING_CREDENTIAL


def test_a_verified_credential_stays_verified_across_a_restart() -> None:
    """Otherwise every restart silently demotes a working key to untested, and
    the operator re-tests the whole Centre after each deploy."""
    from atlas_kernel.credentials.service import Status

    events: list = []
    first = _service(events)
    first.store(provider="anthropic", tenant="t1", secret="k-not-real")
    first.verify(provider="anthropic", tenant="t1",
                 probe=lambda _: (Status.CONNECTED, "accepted"))
    after = _service(events)
    assert after.status(provider="anthropic", tenant="t1") is Status.CONNECTED
    record = after.record(provider="anthropic", tenant="t1")
    assert record is not None and record.last_verification is not None
    assert record.last_verification.detail == "accepted"


def test_a_forgotten_credential_is_not_resurrected_by_the_fold() -> None:
    """A timeline that only ever said "stored" would bring back exactly the
    thing an operator deliberately destroyed."""
    from atlas_kernel.credentials.service import Status

    events: list = []
    first = _service(events)
    first.store(provider="anthropic", tenant="t1", secret="k-not-real")
    first.forget(provider="anthropic", tenant="t1")
    assert _service(events).status(provider="anthropic",
                                   tenant="t1") is Status.NOT_CONFIGURED


def test_a_disabled_credential_stays_disabled_across_a_restart() -> None:
    from atlas_kernel.credentials.service import Status

    events: list = []
    first = _service(events)
    first.store(provider="anthropic", tenant="t1", secret="k-not-real")
    first.set_enabled(provider="anthropic", tenant="t1", enabled=False)
    assert _service(events).status(provider="anthropic",
                                   tenant="t1") is Status.DISABLED


def test_the_latest_event_wins_by_time_not_by_position() -> None:
    """A log that must be replayed in the order it was written is a log with a
    hidden ordering requirement — the same reason `mission.fold` sorts."""
    from atlas_kernel.credentials.service import restore

    events: list = []
    service = _service(events)
    service.store(provider="anthropic", tenant="t1", secret="k-not-real")
    service.set_enabled(provider="anthropic", tenant="t1", enabled=False)
    shuffled = list(reversed(events))
    records = restore(shuffled)
    assert list(records.values())[0].enabled is False


def test_the_timeline_never_carries_the_secret() -> None:
    """`CredentialRecord` has no field holding one, and the event is built from
    the record. This asserts the property rather than trusting the argument."""
    import json

    secret = "sk-a-very-distinctive-value-not-real"
    events: list = []
    service = _service(events)
    service.store(provider="anthropic", tenant="t1", secret=secret)
    service.verify(provider="anthropic", tenant="t1",
                   probe=lambda s: (__import__(
                       "atlas_kernel.credentials.service", fromlist=["Status"]
                   ).Status.CONNECTED, f"provider echoed {s}"))
    written = json.dumps([e.model_dump(mode="json") for e in events])
    assert secret not in written
    for fragment in (secret[:20], secret[-20:]):
        assert fragment not in written


def test_records_stay_in_memory_when_no_timeline_is_given() -> None:
    """The negative control. A service with no timeline must still work — that
    is every test in this file — and must not pretend to be durable."""
    from atlas_kernel.credentials.service import CredentialService, Status
    from atlas_kernel.credentials.vault import MemorySecretStore, Vault

    vault = Vault(MemorySecretStore(), master_key="test-only")
    first = CredentialService(vault)
    first.store(provider="anthropic", tenant="t1", secret="k-not-real")
    assert CredentialService(vault).status(
        provider="anthropic", tenant="t1") is Status.NOT_CONFIGURED
