"""What Qevik will and will not change in the qevik.ai zone.

The token permits any DNS edit in the zone. These tests are about the policy
*below* the token — the refusals that hold even when the credential would allow
the call. They deliberately need neither a token nor a network, because a policy
that can only be tested against the live zone is a policy nobody tests.

The protected-record cases are the ones that matter most: each is a single call
that would take production offline.
"""

from __future__ import annotations

import pytest

from atlas_kernel.infra import (
    ORIGIN_IP,
    PROTECTED,
    Cloudflare,
    CloudflareRefused,
    CloudflareUnavailable,
    check_writable,
)


class Approved:
    approved = True


def test_a_new_subdomain_pointing_here_is_the_one_permitted_shape() -> None:
    check_writable("noa-dental.qevik.ai", "A", ORIGIN_IP)


@pytest.mark.parametrize("name", sorted(PROTECTED))
def test_the_production_records_are_refused(name: str) -> None:
    """Each of these is one call away from taking the whole thing down."""
    with pytest.raises(CloudflareRefused, match="protected"):
        check_writable(name, "A", ORIGIN_IP)


@pytest.mark.parametrize("record_type", ["NS", "MX", "SOA", "CNAME", "TXT", "DNSKEY", "DS"])
def test_only_a_records_are_written(record_type: str) -> None:
    """NS is delegation and MX is mail. Both are out of scope by decision."""
    with pytest.raises(CloudflareRefused):
        check_writable("something.qevik.ai", record_type, ORIGIN_IP)


def test_a_record_may_only_point_at_this_server() -> None:
    with pytest.raises(CloudflareRefused, match="only point at"):
        check_writable("demo.qevik.ai", "A", "1.2.3.4")


def test_a_name_outside_the_zone_is_refused() -> None:
    with pytest.raises(CloudflareRefused, match="not in qevik.ai"):
        check_writable("demo.example.com", "A", ORIGIN_IP)


def test_a_nested_name_is_refused() -> None:
    """`a.www.qevik.ai` is how a check written for one level gets walked past."""
    with pytest.raises(CloudflareRefused, match="single valid subdomain"):
        check_writable("a.www.qevik.ai", "A", ORIGIN_IP)


@pytest.mark.parametrize("label", ["", "-lead", "trail-", "under_score", "UPPER!"])
def test_malformed_labels_are_refused(label: str) -> None:
    with pytest.raises(CloudflareRefused):
        check_writable(f"{label}.qevik.ai", "A", ORIGIN_IP)


def test_a_trailing_dot_and_odd_case_do_not_evade_the_protected_list() -> None:
    """`App.Qevik.ai.` is the same record as `app.qevik.ai`."""
    with pytest.raises(CloudflareRefused, match="protected"):
        check_writable("App.Qevik.AI.", "A", ORIGIN_IP)


def test_there_is_no_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent by design, not by oversight — the one DNS mistake with no undo."""
    monkeypatch.setenv("QEVIK_CLOUDFLARE_API_TOKEN", "not-a-real-token")
    client = Cloudflare()
    try:
        assert not any("delete" in name.lower() for name in dir(client))
    finally:
        client.close()


def test_a_write_without_approval_is_refused_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No network is configured here, so reaching Cloudflare would itself fail.

    That is the point: the refusal must happen before the request, not as a
    consequence of one.
    """
    monkeypatch.setenv("QEVIK_CLOUDFLARE_API_TOKEN", "not-a-real-token")
    client = Cloudflare()
    try:
        with pytest.raises(CloudflareRefused, match="approval"):
            client.point_subdomain("fresh-demo.qevik.ai", approval=None)
        with pytest.raises(CloudflareRefused, match="approval"):
            client.point_subdomain("fresh-demo.qevik.ai", approval=object())
    finally:
        client.close()


def test_an_approved_call_still_obeys_the_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Approval authorises an act; it does not widen what acts are possible."""
    monkeypatch.setenv("QEVIK_CLOUDFLARE_API_TOKEN", "not-a-real-token")
    client = Cloudflare()
    try:
        with pytest.raises(CloudflareRefused, match="protected"):
            client.point_subdomain("app.qevik.ai", approval=Approved())
    finally:
        client.close()


def test_a_missing_token_is_reported_as_absent_not_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QEVIK_CLOUDFLARE_API_TOKEN", raising=False)
    with pytest.raises(CloudflareUnavailable, match="cloudflare.env"):
        Cloudflare()


def test_a_dns_write_is_gated_and_bound_to_the_record() -> None:
    """The gate must know about `dns.point`, and the record must be material.

    If the hostname were not part of the fingerprint, an approval obtained for
    one subdomain would satisfy a write to a different one — which is the whole
    failure mode fingerprint-binding exists to prevent.
    """
    from atlas_kernel.actions.approval_gate import classify, fingerprint

    gate = classify("dns.point")
    assert gate is not None, "dns.point must not be treated as internal"

    one = fingerprint("dns.point", {"record": "demo-a.qevik.ai", "content": ORIGIN_IP})
    other = fingerprint("dns.point", {"record": "demo-b.qevik.ai", "content": ORIGIN_IP})
    assert one != other, "an approval for one hostname would satisfy another"
