"""The crawler will not fetch from inside the network it runs in.

Research fetches a URL somebody supplied — from a customer form, a directory
listing, or a redirect Qevik did not choose — and it fetches it from inside the
deployment. Before `addresses.py`, `http://169.254.169.254/latest/meta-data/`
was a valid "business website": Qevik would fetch it, receive the instance's
cloud credentials, and file them as research on the timeline, readable through
the customer API and quotable in a proposal.

Two tests here matter more than the rest, because they are the ones a naive
implementation fails:

**A name resolving to several addresses is checked at every one.** One public
answer beside one private answer is the standard way past a check that looks at
`[0]`.

**A redirect is checked at every hop.** A public URL that 302s to the metadata
address defeats an entry-point-only check completely — and `follow_redirects`
was on, so httpx walked the chain before anything could look at it.

The last test starts a real HTTP server on loopback and points the crawler at
it, because a guard that has never actually stopped a fetch is a guard nobody
has watched work.
"""

from __future__ import annotations

import http.server
import threading

import httpx
import pytest

from atlas_kernel.research import addresses
from atlas_kernel.research.net import Fetcher

PUBLIC = "93.184.216.34"


def _resolving(monkeypatch, answer: str | None) -> None:
    """Control what names resolve to, instead of asking the real resolver.

    Necessary, not merely tidy. This machine's resolver answers *every* name —
    including `example.com` and names under `.invalid` — from `198.18.0.0/15`,
    which is RFC 2544 benchmark space and correctly classified as private. So
    against ambient DNS the guard refuses everything, "does not resolve" is not
    observable at all, and three tests here passed or failed depending on which
    resolver happened to answer.

    A test of an address policy must control the addresses. `None` means the
    name does not resolve.
    """
    import socket

    def answering(host, *args, **kwargs):
        if answer is None:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answer, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", answering)

# ============================================ what must never be fetched

@pytest.mark.parametrize("url,expected", [
    ("http://169.254.169.254/latest/meta-data/iam/security-credentials/",
     "metadata"),
    ("http://metadata.google.internal/computeMetadata/v1/", "metadata"),
    ("http://127.0.0.1:5432/", "loopback"),
    ("http://localhost:8000/admin", "loopback"),
    ("http://10.0.0.5/internal", "private"),
    ("http://192.168.1.1/", "private"),
    ("http://172.16.0.1/", "private"),
    ("http://[::1]:8080/", "loopback"),
])
def test_an_internal_address_is_refused_with_a_reason(url, expected) -> None:
    why = addresses.reason(url)
    assert why, f"{url} was allowed"
    assert expected in why, why


def test_the_metadata_service_is_named_specifically() -> None:
    """It is the specific prize: on AWS, GCP and Azure it hands out instance
    credentials to anything asking from inside, with no authentication."""
    why = addresses.reason("http://169.254.169.254/")
    assert "cloud metadata service" in why


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://internal.host/secrets",
    "gopher://127.0.0.1:6379/_SET%20foo%20bar",
])
def test_only_http_and_https_are_fetched(url) -> None:
    """`file:///etc/passwd` is a URL, and a crawler that accepts one reads the
    disk it runs on."""
    why = addresses.reason(url)
    assert "not a scheme Qevik fetches" in why


def test_a_public_address_is_allowed(monkeypatch) -> None:
    """The guard must not refuse everything, or it is not a guard — it is an
    outage that happens to be secure."""
    _resolving(monkeypatch, PUBLIC)
    assert addresses.safe("https://example.com") is True


def test_a_url_with_no_host_is_refused() -> None:
    assert "names no host" in addresses.reason("https:///path-only")


def test_a_name_that_does_not_resolve_is_refused_rather_than_attempted(
        monkeypatch) -> None:
    """An unresolvable host is not one we can vouch for."""
    _resolving(monkeypatch, None)
    assert "does not resolve" in addresses.reason("https://nowhere.invalid/")


# ============================================ every address, not the first

def test_every_resolved_address_is_checked(monkeypatch) -> None:
    """One public answer beside one private answer is the standard way past a
    check that looks at `[0]`."""
    import socket

    def both(host, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", both)
    why = addresses.reason("https://looks-fine.example/")
    assert why, "a name resolving to a private address must be refused"
    assert "169.254.169.254" in why


def test_the_check_can_actually_pass(monkeypatch) -> None:
    """Negative control for the test above: with only the public answer, the
    same code path allows it."""
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 0))])
    assert addresses.safe("https://looks-fine.example/") is True


# ============================================ every redirect hop

def test_a_redirect_to_an_internal_address_is_refused(monkeypatch) -> None:
    """The case that defeats an entry-point-only check completely.

    The entry point resolves publicly; only the hop is internal, which is the
    whole shape of the attack.
    """
    _resolving(monkeypatch, PUBLIC)

    def handler(request: httpx.Request) -> httpx.Response:
        if "start" in str(request.url):
            return httpx.Response(302, headers={
                "location": "http://169.254.169.254/latest/meta-data/"})
        return httpx.Response(200, text="<html>should never be reached</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler),
                          follow_redirects=False)
    fetcher = Fetcher("https://example.com", client=client)
    monkeypatch.setattr(fetcher, "_wait", lambda: None)
    page = fetcher.get("https://example.com/start", enforce_robots=False)

    assert "redirect refused" in page.error
    assert "metadata" in page.error
    assert page.html == "", "no body from an internal address may be kept"


def test_the_fetcher_does_not_let_httpx_follow_redirects_itself() -> None:
    """httpx would resolve and connect to each hop before anything here saw it,
    and the hop is exactly what needs checking."""
    fetcher = Fetcher("https://example.com")
    assert fetcher.client.follow_redirects is False


def test_a_redirect_loop_stops(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.com/a"})

    client = httpx.Client(transport=httpx.MockTransport(handler),
                          follow_redirects=False)
    fetcher = Fetcher("https://example.com", client=client)
    monkeypatch.setattr(fetcher, "_wait", lambda: None)
    monkeypatch.setattr(addresses, "check", lambda url: "example.com")

    page = fetcher.get("https://example.com/a", enforce_robots=False)
    assert "redirects" in page.error


# ============================================ a refusal is data, not a crash

def test_a_refused_address_is_recorded_rather_than_raised() -> None:
    """A site we may not reach is a site we could not check — NOT_VERIFIED,
    not a crash that stops the crawl and not a claim about the business."""
    fetcher = Fetcher("http://127.0.0.1")
    page = fetcher.get("http://127.0.0.1/", enforce_robots=False)

    assert page.status == 0
    assert "address refused" in page.error
    assert page.html == ""


# ============================================ watched actually working

@pytest.mark.integration
def test_the_crawler_refuses_a_real_loopback_server() -> None:
    """A guard that has never stopped a real fetch is one nobody has watched.

    This starts an HTTP server on loopback that would serve a secret, points
    the real fetcher at it, and asserts the secret never arrives.
    """
    secret = "SECRET-THAT-MUST-NOT-BE-CRAWLED"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:               # noqa: N802 - stdlib contract
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html>{secret}</html>".encode())

        def log_message(self, *args) -> None:   # noqa: A002 - silence the server
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        page = Fetcher(f"http://127.0.0.1:{port}").get(
            f"http://127.0.0.1:{port}/", enforce_robots=False)

        assert secret not in (page.html or ""), "the crawler reached loopback"
        assert "address refused" in page.error
        assert "loopback" in page.error
    finally:
        server.shutdown()
        server.server_close()


# ============================================ the guard is on unless disabled

def test_the_address_check_is_on_by_default() -> None:
    """The flag exists for `MockTransport`, which opens no socket. Any default
    other than True would make every real deployment opt in to being safe."""
    assert Fetcher("https://example.com").check_addresses is True


def test_the_pipeline_checks_addresses_by_default() -> None:
    """Threaded through rather than derived from whether a client was injected:
    deriving it would silently drop the guard for any deployment that supplied
    a client for connection pooling, and a guard lost by inference is the worst
    kind."""
    import inspect

    from atlas_kernel.research import pipeline

    signature = inspect.signature(pipeline.research)
    assert signature.parameters["check_addresses"].default is True


def test_turning_the_check_off_is_the_only_way_past_it() -> None:
    """Stated as a test so that removing the flag's effect fails here."""
    permissive = Fetcher("http://127.0.0.1", check_addresses=False)
    guarded = Fetcher("http://127.0.0.1")

    assert permissive.check_addresses is False
    assert guarded.get("http://127.0.0.1/",
                       enforce_robots=False).error.startswith("address refused")
