"""Probes, tested on the ways a health check misleads the person reading it.

Without probes `/test` answered 501 for every provider and a stored credential
could never leave `PENDING_CREDENTIAL`. That was honest and useless: nobody
could tell a good key from a typo until a mission failed hours later.

The failures that matter here are not crashes. They are a probe that reports a
network problem as a bad key — sending somebody to rotate a credential that was
fine — and a probe that lets a provider's echo of the request carry the key back
out into a status message somebody screenshots.

No test here makes a network call. Each drives `_classify` and `_ask` directly,
because a suite that needs the internet is a suite that fails on a plane and
gets marked flaky.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel.credentials.probes import (
    PROBES,
    TIMEOUT,
    _ask,
    _classify,
    describe,
)
from atlas_kernel.credentials.service import Status

SECRET = "sk-a-very-distinctive-value-that-is-not-real"


# ============================================ a status a person can act on

def test_success_is_connected() -> None:
    status, detail = _classify(200, "Anthropic")
    assert status is Status.CONNECTED
    assert "Anthropic" in detail


def test_a_rejected_key_says_to_check_the_key() -> None:
    status, detail = _classify(401, "Anthropic")
    assert status is Status.INVALID_CREDENTIAL
    assert "copied whole" in detail


def test_a_forbidden_response_is_not_reported_as_a_bad_key() -> None:
    """403 is usually "right key, wrong plan or missing scope". Telling somebody
    to rotate a working credential wastes an afternoon and changes nothing."""
    status, detail = _classify(403, "Anthropic")
    assert status is Status.INSUFFICIENT_PERMISSION
    assert "probably valid" in detail
    assert "rotate" not in detail.lower() or "rather than replacing" in detail


def test_rate_limiting_says_nothing_about_the_credential() -> None:
    status, detail = _classify(429, "DashScope")
    assert status is Status.RATE_LIMITED
    assert "says nothing either way" in detail


def test_a_provider_outage_is_the_providers_problem() -> None:
    status, detail = _classify(503, "OpenAI")
    assert status is Status.PROVIDER_ERROR
    assert "not the credential" in detail


def test_every_classification_is_distinct_where_the_remedy_differs() -> None:
    """A caller that cannot tell these apart takes the wrong action for three
    of the four."""
    outcomes = {code: _classify(code, "X")[0]
                for code in (200, 401, 403, 429, 500)}
    assert len(set(outcomes.values())) == 5


# ============================================ we could not ask ≠ the key is bad

def test_a_timeout_is_a_network_error_not_an_invalid_credential() -> None:
    """The failure this prevents: an operator rotates a perfectly good key
    because the real problem was egress."""
    def raises(*_: object, **__: object):
        raise httpx.ConnectTimeout("timed out")

    status, detail = _drive(raises)
    assert status is Status.NETWORK_ERROR
    assert "not about the credential" in detail
    assert f"{TIMEOUT:g}s" in detail


def test_a_connection_failure_reports_the_type_not_the_message() -> None:
    """A connection error can quote the URL, and a URL can carry a query
    string."""
    def raises(*_: object, **__: object):
        raise httpx.ConnectError(f"failed connecting with key={SECRET}")

    status, detail = _drive(raises)
    assert status is Status.NETWORK_ERROR
    assert SECRET not in detail
    assert "ConnectError" in detail


def test_the_providers_body_never_reaches_the_detail() -> None:
    """A provider that echoes the request echoes the header, and the header is
    the key. The body is deliberately never consulted."""
    def echoes(*_: object, **__: object):
        return httpx.Response(401, text=f"invalid x-api-key: {SECRET}")

    status, detail = _drive(echoes)
    assert status is Status.INVALID_CREDENTIAL
    assert SECRET not in detail
    assert SECRET[:16] not in detail


def _drive(handler) -> tuple[Status, str]:
    """Run `_ask` with the HTTP call replaced, so nothing leaves the machine."""
    import atlas_kernel.credentials.probes as module

    class Fake:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def get(self, *args, **kwargs): return handler(*args, **kwargs)

    original = module.httpx.Client
    module.httpx.Client = lambda *a, **k: Fake()      # type: ignore[assignment]
    try:
        return _ask("https://example.invalid/models", {"h": SECRET}, "Provider")
    finally:
        module.httpx.Client = original                # type: ignore[assignment]


# ============================================ the registry stays honest

def test_the_providers_the_operator_named_can_be_tested() -> None:
    """Claude and Qwen are the two that were reported broken."""
    assert "anthropic" in PROBES
    assert "qwen" in PROBES


def test_every_probe_names_a_real_integration() -> None:
    """A probe for a provider the Centre does not list is one nothing can
    reach."""
    from atlas_kernel.integrations import BY_ID

    for provider in PROBES:
        assert provider in BY_ID, provider


def test_untestable_providers_are_named_rather_than_hidden() -> None:
    """A provider with no probe answers 501 and says so. The alternative — a
    probe that always passes — turns the Centre into decoration."""
    stated = describe()
    assert stated["untestable"], "some providers genuinely have no probe"
    assert set(stated["testable"]) == set(PROBES)
    assert "501" in stated["note"]


def test_no_probe_generates_anything() -> None:
    """A probe that generated a token would bill the customer for finding out
    whether they can be billed. Read from the source: every probe is a GET to a
    listing endpoint."""
    import ast
    from pathlib import Path

    import atlas_kernel.credentials.probes as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)}
    assert "post" not in calls and "put" not in calls, calls


def test_the_dashscope_region_is_configurable(monkeypatch) -> None:
    """A hard-coded region reports a perfectly good key as invalid for anybody
    outside it."""
    import atlas_kernel.credentials.probes as module

    seen: list[str] = []
    monkeypatch.setattr(module, "_ask",
                        lambda url, headers, provider: (seen.append(url),
                                                        (Status.CONNECTED, ""))[1])
    monkeypatch.setenv("QEVIK_DASHSCOPE_BASE_URL", "https://elsewhere.example/v1/")
    module.qwen(SECRET)
    assert seen == ["https://elsewhere.example/v1/models"]


def test_the_probe_is_never_taken_from_the_request() -> None:
    """A caller-supplied probe is a caller-supplied outbound request carrying
    somebody else's key."""
    from pathlib import Path

    import atlas_kernel.credentials.api as api

    source = Path(api.__file__).read_text(encoding="utf-8")
    assert "app.state" in source and "credential_probes" in source
    assert "body.probe" not in source


@pytest.mark.parametrize("provider", sorted(PROBES))
def test_no_probe_puts_the_secret_in_its_own_url(provider: str) -> None:
    """A key in a query string reaches every proxy log between here and there."""
    import atlas_kernel.credentials.probes as module

    seen: list[str] = []
    original = module._ask
    module._ask = lambda url, headers, name: (      # type: ignore[assignment]
        seen.append(url), (Status.CONNECTED, ""))[1]
    try:
        PROBES[provider](SECRET)
    finally:
        module._ask = original                       # type: ignore[assignment]
    assert seen and SECRET not in seen[0]
