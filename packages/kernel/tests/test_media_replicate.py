"""The first provider that actually generates, and the ways an adapter lies.

The media stack has had assembly, provenance, an approval gate and a YouTube
publisher for months, with a mock at the bottom — so the only thing between
Qevik and generated media was a provider. This is that provider's contract, and
these tests are mostly about what it must *refuse* to do:

* invent a model when the recipe did not name one;
* invent progress the API does not report;
* call a running job finished;
* download something that is not the artefact;
* put the API token into an error message.

Every test drives the real adapter through a fake opener, so the call shapes
under test are the call shapes production uses.
"""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from atlas_kernel.media.providers.base import JobState, ProviderError, RenderRequest
from atlas_kernel.media.providers.replicate import ReplicateProvider, wait


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeAPI:
    """Records requests and replies with queued bodies."""

    def __init__(self, *bodies: dict | bytes) -> None:
        self.bodies = list(bodies)
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, request, timeout=None):
        payload = None
        if getattr(request, "data", None):
            payload = json.loads(request.data.decode())
        self.calls.append((request.get_method(), request.full_url, payload))
        body = self.bodies.pop(0) if self.bodies else {}
        if isinstance(body, bytes):
            return FakeResponse(body)
        return FakeResponse(json.dumps(body).encode())

    @property
    def headers_of_last(self) -> dict:
        return {}


def provider(*bodies, token: str = "test-token") -> tuple[ReplicateProvider, FakeAPI]:
    api = FakeAPI(*bodies)
    return ReplicateProvider(token=token, api_base="https://api.example/v1", opener=api), api


def request_for(**parameters) -> RenderRequest:
    return RenderRequest(recipe_id="video/test", prompt="a cat, cinematic",
                         parameters=parameters)


# --- the recipe decides the model, not the adapter -----------------------------

def test_a_recipe_with_no_model_is_refused() -> None:
    """An adapter that picks a model changes output quality without a commit."""
    p, api = provider()
    with pytest.raises(ProviderError, match="does not name a model"):
        p.submit(request_for())
    assert api.calls == [], "it must refuse before spending anything"


def test_the_named_model_is_the_one_called() -> None:
    p, api = provider({"id": "pred_1"})
    handle = p.submit(request_for(model="black-forest-labs/flux-1.1-pro"))
    assert handle == "pred_1"
    method, url, payload = api.calls[0]
    assert method == "POST"
    assert url.endswith("/models/black-forest-labs/flux-1.1-pro/predictions")
    assert payload["input"]["prompt"] == "a cat, cinematic"


def test_a_pinned_version_goes_to_the_predictions_endpoint() -> None:
    """Pinning a version is how a recipe stops a model changing under it."""
    p, api = provider({"id": "pred_2"})
    p.submit(request_for(model="owner/model", version="abc123"))
    method, url, payload = api.calls[0]
    assert url.endswith("/predictions") and "/models/" not in url
    assert payload["version"] == "abc123"


def test_recipe_parameters_reach_the_model_untouched() -> None:
    """A recipe must be able to set a model-specific input without this adapter
    learning about that model."""
    p, api = provider({"id": "pred_3"})
    p.submit(request_for(model="wan/wan-2.2", num_frames=81, guidance=5.5,
                         aspect_ratio="9:16"))
    _, _, payload = api.calls[0]
    assert payload["input"]["num_frames"] == 81
    assert payload["input"]["aspect_ratio"] == "9:16"
    # Routing fields are not model inputs.
    assert "model" not in payload["input"] and "version" not in payload["input"]


# --- honest states -------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("starting", JobState.QUEUED),
    ("processing", JobState.RUNNING),
    ("succeeded", JobState.SUCCEEDED),
    ("failed", JobState.FAILED),
    ("canceled", JobState.FAILED),
])
def test_provider_states_map_to_ours(raw, expected) -> None:
    p, _ = provider({"id": "x", "status": raw})
    assert p.poll("x").state is expected


def test_an_unknown_state_is_running_not_finished() -> None:
    """A provider that invents a terminal state publishes half a render."""
    p, _ = provider({"id": "x", "status": "something-new"})
    status = p.poll("x")
    assert status.state is JobState.RUNNING
    assert status.finished is False


def test_progress_is_none_because_the_api_does_not_report_it() -> None:
    p, _ = provider({"id": "x", "status": "processing"})
    assert p.poll("x").progress is None


def test_a_failure_carries_the_providers_own_words() -> None:
    """"render failed" throws away the sentence that says whether this is a bad
    prompt, a missing model or an account out of credit."""
    p, _ = provider({"id": "x", "status": "failed", "error": "NSFW content detected"})
    status = p.poll("x")
    assert status.state is JobState.FAILED
    assert "NSFW" in (status.detail or "")


def test_timing_is_reported_only_when_the_api_reports_it() -> None:
    p, _ = provider({"id": "x", "status": "succeeded", "metrics": {"predict_time": 12.5},
                     "output": "https://cdn.example/a.mp4"})
    assert p.poll("x").metadata["predict_time_seconds"] == 12.5

    p2, _ = provider({"id": "x", "status": "succeeded", "output": "https://cdn.example/a.mp4"})
    assert "predict_time_seconds" not in p2.poll("x").metadata


# --- fetching ------------------------------------------------------------------

def test_fetch_streams_the_artefact_to_disk(tmp_path: Path) -> None:
    p, _ = provider({"id": "x", "status": "succeeded", "output": "https://cdn.example/a.mp4"},
                    b"\x00\x01binary video bytes")
    out = p.fetch("x", tmp_path / "clip.mp4")
    assert out.read_bytes() == b"\x00\x01binary video bytes"


def test_fetch_refuses_a_job_that_has_not_finished(tmp_path: Path) -> None:
    p, _ = provider({"id": "x", "status": "processing"})
    with pytest.raises(ProviderError, match="nothing to fetch"):
        p.fetch("x", tmp_path / "clip.mp4")


def test_fetch_refuses_a_success_with_no_output(tmp_path: Path) -> None:
    p, _ = provider({"id": "x", "status": "succeeded", "output": None})
    with pytest.raises(ProviderError, match="no output URL"):
        p.fetch("x", tmp_path / "clip.mp4")


def test_an_empty_download_is_not_an_artefact(tmp_path: Path) -> None:
    """A zero-byte file that exists is worse than one that does not: everything
    downstream treats a path as a rendition."""
    p, _ = provider({"id": "x", "status": "succeeded", "output": "https://cdn.example/a.mp4"},
                    b"")
    with pytest.raises(ProviderError, match="empty file"):
        p.fetch("x", tmp_path / "clip.mp4")
    assert not (tmp_path / "clip.mp4").exists()


def test_the_last_output_is_the_finished_one(tmp_path: Path) -> None:
    """Image models stream progressive frames; the final entry is the render."""
    p, api = provider(
        {"id": "x", "status": "succeeded",
         "output": ["https://cdn.example/step1.png", "https://cdn.example/final.png"]},
        b"final bytes")
    p.fetch("x", tmp_path / "out.png")
    assert api.calls[-1][1] == "https://cdn.example/final.png"


def test_a_dict_output_is_understood(tmp_path: Path) -> None:
    p, api = provider({"id": "x", "status": "succeeded",
                       "output": {"video": "https://cdn.example/v.mp4"}}, b"v")
    p.fetch("x", tmp_path / "v.mp4")
    assert api.calls[-1][1] == "https://cdn.example/v.mp4"


# --- configuration is a state, not a crash -------------------------------------

def test_a_missing_token_is_a_named_configuration_state() -> None:
    p = ReplicateProvider(token="", api_base="https://api.example/v1", opener=FakeAPI())
    with pytest.raises(ProviderError, match="QEVIK_REPLICATE_API_TOKEN is not set"):
        p.submit(request_for(model="owner/model"))


def test_an_http_error_never_carries_the_token() -> None:
    """An adapter that puts its credential in an exception puts it in a log."""
    secret = "sk-do-not-leak-me"

    def failing(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 402, "Payment Required", {},
                                     io.BytesIO(b'{"detail":"out of credit"}'))

    p = ReplicateProvider(token=secret, api_base="https://api.example/v1", opener=failing)
    with pytest.raises(ProviderError) as caught:
        p.submit(request_for(model="owner/model"))
    assert "402" in str(caught.value) and "out of credit" in str(caught.value)
    assert secret not in str(caught.value)


# --- waiting -------------------------------------------------------------------

def test_wait_returns_when_the_job_finishes() -> None:
    p, _ = provider({"id": "x", "status": "processing"},
                    {"id": "x", "status": "processing"},
                    {"id": "x", "status": "succeeded", "output": "https://cdn/a.mp4"})
    status = wait(p, "x", interval=0, sleep=lambda _: None)
    assert status.state is JobState.SUCCEEDED


def test_wait_says_the_job_may_still_be_running_elsewhere() -> None:
    """A timeout here is not a cancellation there, and the message says so —
    otherwise somebody submits the same paid render again."""
    api = FakeAPI(*[{"id": "x", "status": "processing"}] * 50)
    p = ReplicateProvider(token="t", api_base="https://api.example/v1", opener=api)
    with pytest.raises(ProviderError) as caught:
        wait(p, "x", timeout=-1, interval=0, sleep=lambda _: None)
    message = str(caught.value)
    assert "may still be running on the provider" in message
    assert "not a cancellation there" in message


# --- the composition point ------------------------------------------------------

def test_an_unconfigured_installation_has_no_providers(monkeypatch) -> None:
    """The honest answer to "can you make an image" when nothing is connected.

    Registering a provider that would fail at the first call turns a
    configuration state into a render failure, which is the harder of the two to
    diagnose.
    """
    from atlas_kernel.media.registry import NoProviderAvailable, from_environment

    monkeypatch.delenv("QEVIK_REPLICATE_API_TOKEN", raising=False)
    registry = from_environment()
    assert registry.names() == []
    with pytest.raises(NoProviderAvailable, match="image.generate"):
        registry.resolve("image.generate")


def test_a_configured_token_registers_image_and_video(monkeypatch) -> None:
    from atlas_kernel.media.registry import from_environment

    monkeypatch.setenv("QEVIK_REPLICATE_API_TOKEN", "r8_test")
    registry = from_environment()
    assert registry.names() == ["replicate"]
    for capability in ("image.generate", "video.generate"):
        assert registry.resolve(capability).name == "replicate"


def test_the_cloud_provider_is_excluded_when_cloud_is_disabled(monkeypatch) -> None:
    """Local-first is a policy the registry already enforces; a cloud provider
    that ignored `allow_cloud=False` would quietly bill for work a deployment
    said must stay on its own machines."""
    from atlas_kernel.media.registry import NoProviderAvailable, from_environment

    monkeypatch.setenv("QEVIK_REPLICATE_API_TOKEN", "r8_test")
    registry = from_environment(allow_cloud=False)
    with pytest.raises(NoProviderAvailable, match="cloud providers are disabled"):
        registry.resolve("image.generate")


def test_no_price_is_invented_for_a_provider_that_bills_per_model() -> None:
    """A fabricated cost is used to choose between providers and is wrong in a
    way nobody can see."""
    from atlas_kernel.media.registry import from_environment
    import os

    os.environ["QEVIK_REPLICATE_API_TOKEN"] = "r8_test"
    try:
        registration = from_environment().resolve("image.generate")
        assert registration.cost_per_second == 0.0
        assert "reported after the fact" in registration.labels["billing"]
    finally:
        os.environ.pop("QEVIK_REPLICATE_API_TOKEN", None)


def test_one_provider_can_serve_more_than_one_capability() -> None:
    """The registry de-duplicated by provider name alone, so registering the
    same provider for a second capability evicted the first. Nothing caught it
    because every registration until now used exactly one capability."""
    from atlas_kernel.media.registry import MediaProviderRegistry, ProviderRegistration

    class Both:
        name = "both"

    registry = MediaProviderRegistry()
    provider = Both()
    registry.register(ProviderRegistration(provider=provider, capability="image.generate"))
    registry.register(ProviderRegistration(provider=provider, capability="video.generate"))

    assert registry.resolve("image.generate").name == "both"
    assert registry.resolve("video.generate").name == "both"


def test_re_registering_the_same_pair_replaces_rather_than_duplicates() -> None:
    from atlas_kernel.media.registry import MediaProviderRegistry, ProviderRegistration

    class P:
        name = "p"

    registry = MediaProviderRegistry()
    registry.register(ProviderRegistration(provider=P(), capability="image.generate",
                                           cost_per_second=1.0))
    registry.register(ProviderRegistration(provider=P(), capability="image.generate",
                                           cost_per_second=2.0))
    assert registry.resolve("image.generate").cost_per_second == 2.0
    assert registry.names() == ["p"]
