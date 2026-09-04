"""Measured, not claimed.

A provider's catalogue is not a list of what you can run. NVIDIA's
`GET /v1/models` lists 81 models and most of them answer 404 "Function not
found", 410 "Gone" or 503 — with a key that works from the same machine a
second later. A page built from a catalogue is a page of offerings nobody has
tried, presented as an inventory.

So these tests are about the three states, and mostly about the third one: a
model nobody has called has not failed, and a fresh deployment is made entirely
of those.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_kernel.llm import benchmark
from atlas_kernel.llm.providers import MODELS, AnthropicProvider, OpenAICompatibleProvider
from atlas_kernel.qevik import Wiring, create_app

SPEC = MODELS["qwen-plus"]


def _provider(handler):
    return OpenAICompatibleProvider(
        name="qwen", key_env="X", key="k",
        client=httpx.Client(transport=httpx.MockTransport(handler)))


def _answers(text="up", prompt_tokens=11, completion_tokens=2):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens,
                      "completion_tokens": completion_tokens}})
    return handler


class TestTheThreeStates:
    def test_a_model_that_answers_is_reached_with_its_numbers(self) -> None:
        m = benchmark.measure(_provider(_answers()), SPEC)
        assert m.state is benchmark.State.REACHED
        assert m.input_tokens == 11 and m.output_tokens == 2
        assert m.latency_ms is not None
        assert m.cost_usd == SPEC.cost_usd(11, 2)
        assert m.answered == "up"
        assert m.reason == ""

    def test_a_provider_that_declines_is_refused_and_says_why(self) -> None:
        """404 'Function not found' is the single most common answer in
        NVIDIA's catalogue. It is a fact about the model, and it belongs on the
        page in the provider's own words."""
        handler = lambda r: httpx.Response(  # noqa: E731
            404, json={"detail": "Function 'abc': Not found"})
        m = benchmark.measure(_provider(handler), SPEC)
        assert m.state is benchmark.State.REFUSED
        assert "404" in m.reason

    def test_a_call_that_never_completed_says_nothing_about_the_model(self) -> None:
        """A disconnect is not a verdict. Recording it as REFUSED would put a
        fault on a model that may be perfectly fine."""
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("server disconnected")

        m = benchmark.measure(_provider(handler), SPEC)
        assert m.state is benchmark.State.NOT_VERIFIED
        assert "could not reach" in m.reason


    def test_unreachable_is_its_own_type_and_not_a_refusal(self) -> None:
        """The distinction has to exist in the provider, not be guessed at here.

        Transport failures were raised as a bare `LLMError` — the same type a
        404 raises — so a benchmark reading them apart would have been reading a
        message string. `Unreachable` makes it a fact about the exception."""
        from atlas_kernel.llm.models import LLMError, NotConfigured, Unreachable

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("server disconnected")

        with pytest.raises(Unreachable):
            _provider(handler).complete([], SPEC, max_tokens=4, temperature=0)
        assert issubclass(Unreachable, LLMError)
        assert not issubclass(Unreachable, NotConfigured)

    def test_measuring_never_raises(self) -> None:
        """A benchmark that stops at the first refusal measures the models
        before the alphabetically unlucky one and nothing after it."""
        def handler(request: httpx.Request) -> httpx.Response:
            raise ValueError("something entirely unexpected")

        assert benchmark.measure(_provider(handler), SPEC).state is (
            benchmark.State.NOT_VERIFIED)

    def test_a_refusal_never_carries_the_key(self) -> None:
        handler = lambda r: httpx.Response(401, text="key was: sk-SECRET-VALUE")  # noqa: E731
        m = benchmark.measure(_provider(handler), SPEC)
        assert "sk-SECRET-VALUE" not in m.reason
        assert "sk-SECRET-VALUE" not in json.dumps(m.as_dict())


class TestTheStore:
    def test_an_absent_file_is_nothing_measured_not_an_error(self, tmp_path) -> None:
        store = benchmark.Store(tmp_path / "nope.jsonl")
        assert store.read() == []
        assert store.latest() == {}

    def test_the_latest_measurement_wins_by_position(self, tmp_path) -> None:
        """By position, not timestamp: the file is append-only, so the last line
        for a model is the last measurement of it, and comparing timestamps
        would let a clock skew reorder history."""
        store = benchmark.Store(tmp_path / "m.jsonl")
        store.record(benchmark.Measurement(model="a", provider="p", at="2026-01-02",
                                           state=benchmark.State.REFUSED))
        store.record(benchmark.Measurement(model="a", provider="p", at="2026-01-01",
                                           state=benchmark.State.REACHED,
                                           latency_ms=12))
        assert store.latest()["a"]["state"] == "REACHED"

    def test_a_line_that_will_not_parse_is_counted_not_fatal(self, tmp_path) -> None:
        path = tmp_path / "m.jsonl"
        store = benchmark.Store(path)
        store.record(benchmark.Measurement(model="a", provider="p", at="x",
                                           state=benchmark.State.REACHED))
        with path.open("a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        assert len(store.read()) == 1
        assert store.corrupt == 1

    def test_a_run_records_as_it_goes(self, tmp_path) -> None:
        """A run that dies halfway has still measured half, and throwing that
        away because the process stopped is how a slow provider costs a whole
        benchmark."""
        from atlas_kernel.llm.registry import Registration

        store = benchmark.Store(tmp_path / "m.jsonl")
        good = Registration(provider=_provider(_answers()), spec=SPEC)
        broken = Registration(provider=AnthropicProvider(key=""),
                              spec=MODELS["claude-sonnet-5"])
        benchmark.run([good, broken], store)
        assert {row["model"] for row in store.read()} == {
            "qwen-plus", "claude-sonnet-5"}


class TestTheSummary:
    def test_it_names_the_fastest_thing_that_answered(self) -> None:
        latest = {
            "a": {"model": "a", "state": "REACHED", "latency_ms": 900},
            "b": {"model": "b", "state": "REACHED", "latency_ms": 120},
            "c": {"model": "c", "state": "REFUSED"},
        }
        found = benchmark.summary(latest)
        assert found["fastest"] == {"model": "b", "latency_ms": 120}
        assert found["counts"]["REACHED"] == 2

    def test_nothing_reached_has_no_fastest_rather_than_a_zero(self) -> None:
        assert benchmark.summary({"a": {"model": "a", "state": "REFUSED"}})[
            "fastest"] is None

    def test_it_scores_no_quality(self) -> None:
        """One trivial prompt cannot measure quality, and a number that looked
        like a quality score would be believed."""
        import inspect

        source = inspect.getsource(benchmark)
        for forbidden in ("def score", "quality_score", "rank(", "rating"):
            assert forbidden not in source, source
        assert "cannot" in benchmark.summary({})["note"]


class TestTheRoute:
    @pytest.fixture
    def client(self, tmp_path):
        app = create_app(Wiring(repository_root=tmp_path,
                                vault_path=tmp_path / "vault.json",
                                model_measurements=tmp_path / "m.jsonl"))
        with TestClient(app) as test_client:
            yield test_client

    def test_a_registered_model_nobody_called_is_not_verified(self, client) -> None:
        body = client.get("/api/models/benchmark").json()
        assert body["known"] is True
        assert all(row["state"] == "NOT_VERIFIED" for row in body["rows"])

    def test_no_state_directory_is_not_every_model_failing(self, tmp_path) -> None:
        app = create_app(Wiring(repository_root=tmp_path,
                                vault_path=tmp_path / "vault.json"))
        with TestClient(app) as client:
            body = client.get("/api/models/benchmark").json()
        assert body["known"] is False
        assert "not the same as every model failing" in body["detail"]

    def test_a_measurement_reaches_the_route(self, client, tmp_path) -> None:
        benchmark.Store(tmp_path / "m.jsonl").record(benchmark.Measurement(
            model="qwen-plus", provider="qwen", state=benchmark.State.REACHED,
            at="2026-09-04T10:00:00+00:00", latency_ms=311, cost_usd=0.000005))
        rows = {r["model"]: r for r in client.get("/api/models/benchmark").json()["rows"]}
        assert rows["qwen-plus"]["state"] == "REACHED"
        assert rows["qwen-plus"]["latency_ms"] == 311

    def test_a_measurement_for_an_unregistered_model_still_shows(self, client,
                                                                 tmp_path) -> None:
        """It would otherwise vanish the day a model is removed from the
        registry, taking the record of what it did with it."""
        benchmark.Store(tmp_path / "m.jsonl").record(benchmark.Measurement(
            model="retired/model", provider="nvidia",
            state=benchmark.State.REFUSED, at="2026-09-04T10:00:00+00:00",
            reason="410 Gone"))
        rows = {r["model"]: r for r in client.get("/api/models/benchmark").json()["rows"]}
        assert rows["retired/model"]["registered"] is False
        assert rows["retired/model"]["state"] == "REFUSED"
