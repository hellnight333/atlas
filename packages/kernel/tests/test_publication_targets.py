"""Publishing, tested on the states between "worked" and "failed".

A publication that half-worked is worse than one that failed: the customer's old
page is gone and the new one is broken, and nothing reports an error. So there is
no partial success in this module, and most of these tests are about the states
that could pretend to be one.

The other half is about the domain. Publishing to a hostname somebody typed is
publishing to whatever they typed — a competitor's, a typo, or one they do not
own — so verification is a DNS record only the owner can create, and the three
outcomes of looking for it are kept apart: present, absent, and *we could not
look*, which is our outage and must never read as absent.
"""

from __future__ import annotations

import pytest

from atlas_kernel.publication.targets import (
    CloudflareTarget,
    Deployment,
    LocalTarget,
    MissingCredential,
    MissingInfrastructure,
    PendingCredentialTarget,
    PendingInfrastructureTarget,
    PublicationTarget,
    PublishState,
    VerificationState,
    deploy,
    describe,
    domain_for,
    verify,
)

TENANT = "tenant-alpha"


@pytest.fixture
def site(tmp_path):
    return tmp_path / "site"


@pytest.fixture
def domain():
    return domain_for("alhamra.ae", tenant=TENANT)


# ============================================ the domain is proved, not typed

def test_a_domain_is_not_publishable_until_it_is_verified(domain) -> None:
    assert domain.state is VerificationState.NOT_CHECKED
    assert domain.publishable is False


def test_the_verification_record_can_only_be_created_by_the_owner(domain) -> None:
    """That is the whole proof: a TXT record in a zone we cannot write to."""
    record = domain.record
    assert record["type"] == "TXT"
    assert record["value"] == domain.token
    assert "controls this domain" in record["note"]


def test_one_tenants_token_cannot_verify_anothers_domain() -> None:
    """Or a tenant could publish to a domain another tenant proved."""
    mine = domain_for("alhamra.ae", tenant=TENANT)
    theirs = domain_for("alhamra.ae", tenant="tenant-beta")
    assert mine.token != theirs.token
    assert verify(mine, records=(theirs.token,)).state is VerificationState.FAILED


def test_a_present_record_verifies(domain) -> None:
    checked = verify(domain, records=(domain.token, "v=spf1 -all"))
    assert checked.state is VerificationState.VERIFIED
    assert checked.publishable is True
    assert checked.checked_at is not None


def test_an_absent_record_fails_and_says_the_lookup_worked(domain) -> None:
    """Distinct from a failed lookup: retrying this will not help."""
    checked = verify(domain, records=("v=spf1 -all", "google-site-verification=x"))
    assert checked.state is VerificationState.FAILED
    assert "the lookup worked and the record is absent" in checked.detail


def test_a_failed_lookup_is_unknown_and_never_absent(domain) -> None:
    """Telling a customer their record is missing when we could not look is the
    same error as publishing on the strength of our own outage."""
    checked = verify(domain, records=None)
    assert checked.state is VerificationState.UNKNOWN
    assert checked.publishable is False
    assert "nothing was established" in checked.detail


def test_a_malformed_hostname_is_refused_rather_than_guessed() -> None:
    """Guessing what somebody meant is how a site reaches the wrong domain."""
    for bad in ("not a domain", "http://", "alhamra", "-bad.ae", ""):
        with pytest.raises(MissingInfrastructure):
            domain_for(bad, tenant=TENANT)


def test_a_url_is_reduced_to_its_hostname() -> None:
    assert domain_for("https://www.alhamra.ae/about?x=1",
                      tenant=TENANT).hostname == "alhamra.ae"


# ============================================ nothing goes live unauthorised

def test_a_ready_bundle_is_not_published_without_authorisation(site) -> None:
    """READY_TO_PUBLISH is not PUBLISHED, and this is where that stops being a
    slogan."""
    result = deploy(LocalTarget(site), {"index.html": "<p>hi</p>"})
    assert result.state is PublishState.NOT_AUTHORISED
    assert not site.exists(), "nothing may be written"
    assert "not a failure" in result.detail


def test_not_authorised_is_not_a_failure(site) -> None:
    """A caller that treats them the same will retry something nobody agreed to."""
    result = deploy(LocalTarget(site), {"index.html": "<p>hi</p>"})
    assert result.state is not PublishState.FAILED
    assert result.succeeded is False


def test_a_public_target_refuses_an_unverified_domain(domain) -> None:
    result = deploy(CloudflareTarget(), {"index.html": "x"}, domain=domain,
                    authorised=True)
    assert result.state is PublishState.FAILED
    assert "not verified" in result.detail


# ============================================ all of it, or none of it

def test_publishing_writes_every_file(site) -> None:
    files = {"index.html": "<p>home</p>", "about.html": "<p>about</p>",
             "sitemap.xml": "<urlset/>"}
    result = deploy(LocalTarget(site), files, authorised=True)

    assert result.state is PublishState.PUBLISHED
    assert set(result.written) == set(files)
    for name, body in files.items():
        assert (site / name).read_text(encoding="utf-8") == body


def test_a_second_publication_replaces_the_first_atomically(site) -> None:
    """A target overwriting file by file leaves a live site half-replaced."""
    target = LocalTarget(site)
    deploy(target, {"index.html": "v1", "old.html": "gone"}, authorised=True)
    deploy(target, {"index.html": "v2"}, authorised=True)

    assert (site / "index.html").read_text(encoding="utf-8") == "v2"
    assert not (site / "old.html").exists(), "the old file must not survive"


def test_publishing_nothing_is_a_failure_not_an_empty_success(site) -> None:
    result = deploy(LocalTarget(site), {}, authorised=True)
    assert result.state is PublishState.FAILED
    assert "nothing to publish" in result.detail


def test_the_bundle_identity_travels_with_the_deployment(site) -> None:
    """So a live site can be proved to be the artefact that was approved."""
    result = deploy(LocalTarget(site), {"index.html": "x"},
                    content_hash="abc123", authorised=True)
    assert result.content_hash == "abc123"


# ============================================ rollback

def test_a_rollback_restores_the_previous_version(site) -> None:
    target = LocalTarget(site)
    deploy(target, {"index.html": "v1"}, authorised=True)
    second = deploy(target, {"index.html": "v2"}, authorised=True)

    undone = target.rollback(second)
    assert undone.state is PublishState.ROLLED_BACK
    assert (site / "index.html").read_text(encoding="utf-8") == "v1"


def test_rolling_back_a_first_publication_says_there_is_nothing_to_undo(site
                                                                       ) -> None:
    """Silently succeeding would leave the customer believing the site was
    withdrawn."""
    target = LocalTarget(site)
    first = deploy(target, {"index.html": "v1"}, authorised=True)
    undone = target.rollback(first)
    assert undone.state is PublishState.FAILED
    assert "first publication" in undone.detail


def test_a_failed_deployment_records_what_it_managed_to_write() -> None:
    """A partial upload is the case rollback exists for, so it must be known."""
    partial = Deployment(target="x", state=PublishState.FAILED,
                         written=("index.html", "about.html"))
    assert partial.written, "a failure with no record is a failure nobody can undo"
    assert partial.succeeded is False


# ============================================ two kinds of not-configured

def test_a_missing_credential_and_missing_infrastructure_are_different() -> None:
    """Collapsing them into "not configured" makes provisioning a server look
    like something solvable by typing a password."""
    key = PendingCredentialTarget("cloudflare", credential="QEVIK_X")
    machine = PendingInfrastructureTarget("own-host", needs="a server and a DNS record")

    with pytest.raises(MissingCredential):
        key.publish({"a": "b"})
    with pytest.raises(MissingInfrastructure):
        machine.publish({"a": "b"})
    assert not issubclass(MissingInfrastructure, MissingCredential)


def test_describe_names_the_exact_human_action() -> None:
    key = describe(PendingCredentialTarget("x", credential="QEVIK_X"))
    assert key["status"] == "PENDING_CREDENTIAL"
    assert key["credential"] == "QEVIK_X"
    assert "Credential Centre" in key["action"]

    machine = describe(PendingInfrastructureTarget("y", needs="a host"))
    assert machine["status"] == "PENDING_INFRASTRUCTURE"
    assert machine["needs"] == "a host"


def test_the_local_target_says_it_serves_no_public_domain(site) -> None:
    """Which is why a customer served this way receives a bundle, not a site."""
    described = describe(LocalTarget(site))
    assert described["status"] == "CONNECTED"
    assert described["publishes"] is True
    assert "bundle rather than a site" in described["note"]


def test_a_refusal_is_recorded_rather_than_raised(domain) -> None:
    """The caller needs the reason on the publication record; a target that
    cannot publish is a fact about this deployment, not a crash."""
    verified = verify(domain, records=(domain.token,))
    result = deploy(CloudflareTarget(), {"index.html": "x"}, domain=verified,
                    authorised=True)
    assert result.state is PublishState.FAILED
    assert "QEVIK_CLOUDFLARE_API_TOKEN" in result.detail


# ============================================ Cloudflare, as far as it goes

def test_the_cloudflare_manifest_matches_the_bundle() -> None:
    """A manifest disagreeing with the bundle uploads the wrong files under the
    right names."""
    files = {"index.html": "<p>a</p>", "about.html": "<p>b</p>"}
    manifest = CloudflareTarget.manifest(files)
    assert set(manifest) == {"/index.html", "/about.html"}
    assert len(set(manifest.values())) == 2, "different content, different hashes"
    assert manifest == CloudflareTarget.manifest(files), "deterministic"


def test_the_cloudflare_refusal_names_the_token_and_the_permission() -> None:
    """Both are things only a person can produce, and neither can be derived."""
    with pytest.raises(MissingCredential) as refused:
        CloudflareTarget().publish({"a": "b"},
                                   domain=verify(domain_for("x.ae", tenant=TENANT),
                                                 records=(domain_for("x.ae", tenant=TENANT).token,)))
    assert "QEVIK_CLOUDFLARE_API_TOKEN" in str(refused.value)
    assert "Pages:Edit" in str(refused.value)


def test_the_upload_call_is_deliberately_unwritten() -> None:
    """Written blind against an API nobody can run, it would read as finished
    and fail on the first real call."""
    from pathlib import Path

    from atlas_kernel.publication import targets

    source = Path(targets.__file__).read_text(encoding="utf-8")
    assert "httpx" not in source and "requests" not in source
    assert "deliberately unwritten" in source


def test_every_target_satisfies_the_protocol(site) -> None:
    for target in (LocalTarget(site), CloudflareTarget(),
                   PendingCredentialTarget("x", credential="Y"),
                   PendingInfrastructureTarget("z", needs="a host")):
        assert isinstance(target, PublicationTarget), target
