"""Ask a provider whether a key actually works.

A probe is the difference between "somebody pasted something" and "this
connects". Without one, `/test` answers 501 and every stored credential stays
`PENDING_CREDENTIAL` for ever — which is honest, and useless: the operator has
no way to find out whether the key they entered is the right one until a mission
fails hours later.

## What a probe must not do

**Never return the provider's raw error text.** A provider that echoes the
request echoes the header, and the header is the key. Each probe here maps a
status code to one of `Status`'s values and writes its own sentence.
`_safe()` in the service is a second net, not the first one.

**Never be supplied by the caller.** The API takes probes from
`app.state.credential_probes`, not from the request body — a caller-supplied
probe is a caller-supplied outbound request carrying somebody else's key.

**Distinguish "wrong key" from "we could not ask".** `INVALID_CREDENTIAL` and
`NETWORK_ERROR` look the same from here and mean opposite things to the person
reading the screen: one is a typo, the other is a firewall. Reporting a timeout
as an invalid key sends somebody to rotate a credential that was fine.

## The cheapest authenticated call

Each probe lists models. It is the smallest authenticated request these
providers offer, it costs nothing, and it changes nothing — a probe that
generated a token would bill the customer for finding out whether they can be
billed.

**Google Places has no probe, deliberately.** It bills every authenticated
request and offers no free listing endpoint, so a Test button would charge for
each press — and a button is pressed more than once. It is verified instead by
a discovery run returning businesses with a phone or a website, which its
registry entry states. A probe was written for it and removed; if you are about
to add one, this is the reason not to.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import httpx

from .service import Status

#: Short. A probe is a health check, and an operator waiting on a spinner needs
#: an answer well before a request would otherwise give up.
TIMEOUT = 12.0

Probe = Callable[[str], tuple[Status, str]]


def _classify(code: int, provider: str) -> tuple[Status, str]:
    """One HTTP status into one of ours, with our own words.

    The provider's body is deliberately not consulted. It is the one place a
    key can come back out, and no probe needs it to decide what happened.
    """
    if 200 <= code < 300:
        return Status.CONNECTED, f"{provider} accepted the credential"
    if code in (401, 403):
        # 403 is not always "wrong key" — it is often "right key, wrong plan or
        # missing scope", and telling somebody to rotate a working credential
        # wastes an afternoon.
        if code == 401:
            return Status.INVALID_CREDENTIAL, (
                f"{provider} rejected the credential. Check it was copied "
                "whole, and that it belongs to this account.")
        return Status.INSUFFICIENT_PERMISSION, (
            f"{provider} recognised the credential and refused the request. "
            "The key is probably valid but lacks access — check the plan or "
            "the scopes rather than replacing it.")
    if code == 429:
        return Status.RATE_LIMITED, (
            f"{provider} is rate limiting. The credential may be fine; this "
            "says nothing either way.")
    if code >= 500:
        return Status.PROVIDER_ERROR, (
            f"{provider} returned {code}. Their problem, not the credential's.")
    return Status.PROVIDER_ERROR, f"{provider} returned {code}"


def _ask(url: str, headers: dict[str, str], provider: str
         ) -> tuple[Status, str]:
    """One GET, and every failure turned into a status rather than an exception.

    `NETWORK_ERROR` is its own answer. Collapsing it into INVALID_CREDENTIAL
    would send somebody to rotate a key when the real problem was egress.
    """
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
            return _classify(client.get(url, headers=headers).status_code,
                             provider)
    except httpx.TimeoutException:
        return Status.NETWORK_ERROR, (
            f"{provider} did not answer within {TIMEOUT:g}s. This is about "
            "reaching them, not about the credential.")
    except httpx.HTTPError as failure:
        # The type, never the message: a connection error can quote the URL,
        # and a URL can carry a query string.
        return Status.NETWORK_ERROR, (
            f"{provider} could not be reached ({type(failure).__name__}). "
            "This is about the network, not the credential.")


def anthropic(secret: str) -> tuple[Status, str]:
    """Claude. `x-api-key`, and a version header the API requires."""
    return _ask("https://api.anthropic.com/v1/models",
                {"x-api-key": secret, "anthropic-version": "2023-06-01"},
                "Anthropic")


def openai(secret: str) -> tuple[Status, str]:
    return _ask("https://api.openai.com/v1/models",
                {"Authorization": f"Bearer {secret}"}, "OpenAI")


def deepseek(secret: str) -> tuple[Status, str]:
    return _ask("https://api.deepseek.com/models",
                {"Authorization": f"Bearer {secret}"}, "DeepSeek")


#: Where DashScope lives for this deployment. Read from the environment because
#: the region differs between accounts, and a hard-coded region reports a
#: perfectly good key as invalid for anybody outside it.
DASHSCOPE_DEFAULT = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


def qwen(secret: str) -> tuple[Status, str]:
    """Qwen, through DashScope's OpenAI-compatible surface."""
    base = (os.environ.get("QEVIK_DASHSCOPE_BASE_URL") or DASHSCOPE_DEFAULT
            ).rstrip("/")
    return _ask(f"{base}/models", {"Authorization": f"Bearer {secret}"},
                "DashScope")


def stripe(secret: str) -> tuple[Status, str]:
    return _ask("https://api.stripe.com/v1/balance",
                {"Authorization": f"Bearer {secret}"}, "Stripe")


def cloudflare(secret: str) -> tuple[Status, str]:
    return _ask("https://api.cloudflare.com/client/v4/user/tokens/verify",
                {"Authorization": f"Bearer {secret}"}, "Cloudflare")


#: Every provider that can actually be tested. A provider absent from here gets
#: a 501 that says so, which is the honest answer — better than a probe that
#: always passes and turns the Credential Centre into decoration.
PROBES: dict[str, Probe] = {
    "anthropic": anthropic,
    "qwen": qwen,
    "openai": openai,
    "deepseek": deepseek,
    "stripe": stripe,
    "cloudflare": cloudflare,
}


def describe() -> dict:
    """Which providers can be tested, and which cannot — named, not counted."""
    from ..integrations import INTEGRATIONS

    every = {i.id for i in INTEGRATIONS}
    return {
        "testable": sorted(PROBES),
        "untestable": sorted(every - set(PROBES)),
        "note": ("A provider with no probe answers 501 rather than pretending. "
                 "Its credential can still be stored and stays "
                 "PENDING_CREDENTIAL until something uses it."),
    }
