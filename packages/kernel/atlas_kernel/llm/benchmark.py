"""What each model actually did when it was called, and when.

A provider's catalogue is not a list of what you can run. NVIDIA's
`GET /v1/models` lists 81 models and most of them answer 404 "Function not
found", 410 "Gone", or 503 — with a key that works. A page built from a
catalogue is a page of offerings nobody has tried.

So this records calls. One measurement per model per run, with the same three
states the rest of this codebase uses, kept distinct because they need opposite
responses from a person:

  REACHED       called, answered, tokens counted, latency measured
  REFUSED       called, and the provider declined — carrying the reason it gave
  NOT_VERIFIED  the call could not be completed, or was never made

`NOT_VERIFIED` is the one that matters. A model nobody has called is not a
model that fails, and drawing them the same way either invents a fault or
hides one. It is also what an operator sees on a fresh deployment, where
everything is unmeasured and nothing is broken.

**Measured through the same adapters production uses.** A second HTTP client
here would be a second answer to "does this work" — the one that measures well
while the one that runs fails, or the reverse. The provider, the base URL, the
headers and the timeout are whatever `llm.providers` does.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Where measurements live, under the deployment's state directory. JSONL and
#: append-only, like every other record here: a measurement is something that
#: happened, and the previous one is how you see that a model got slower.
FILE = "model_measurements.jsonl"

#: What every model is asked. Trivial on purpose — this measures whether the
#: model is reachable and how fast it answers, not how good it is. A benchmark
#: that scored quality would be scoring one prompt, and reporting that as a
#: model's quality is worse than reporting nothing.
PROMPT = "Reply with exactly: up"
MAX_TOKENS = 24


class State(StrEnum):
    REACHED = "REACHED"
    REFUSED = "REFUSED"
    NOT_VERIFIED = "NOT_VERIFIED"


@dataclass(frozen=True)
class Measurement:
    """One call to one model."""

    model: str
    provider: str
    state: State
    at: str
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    #: Priced from the model's own spec, so the figure here and the figure in a
    #: mission's ledger come from one table.
    cost_usd: float | None = None
    #: Why it was refused, in the provider's words, never carrying a key.
    reason: str = ""
    answered: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model, "provider": self.provider,
            "state": self.state.value, "at": self.at,
            "latency_ms": self.latency_ms, "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens, "cost_usd": self.cost_usd,
            "reason": self.reason, "answered": self.answered,
        }


@dataclass
class Store:
    """The measurements file. Absent is a real state and is not an error."""

    path: Path
    #: Lines that would not parse, counted rather than raised — a rotting file
    #: should be visible, not fatal to a page that is otherwise fine.
    corrupt: int = field(default=0)

    def record(self, measurement: Measurement) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(measurement.as_dict()) + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        self.corrupt = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                self.corrupt += 1
        return rows

    def latest(self) -> dict[str, dict[str, Any]]:
        """The most recent measurement per model.

        By position rather than by timestamp: the file is append-only, so the
        last line for a model is the last measurement of it, and comparing
        timestamps would let a clock skew reorder history.
        """
        newest: dict[str, dict[str, Any]] = {}
        for row in self.read():
            name = row.get("model")
            if name:
                newest[name] = row
        return newest


def measure(provider: Any, spec: Any, *, now: str = "") -> Measurement:
    """Call one model through its own adapter and record what happened.

    Never raises. A benchmark that stops at the first refusal measures the
    models before the alphabetically unlucky one and nothing after it.
    """
    from .models import LLMError, Message, Role, Unreachable

    stamp = now or datetime.now(UTC).isoformat()
    started = time.monotonic()
    try:
        completion = provider.complete(
            [Message(role=Role.USER, content=PROMPT)], spec,
            max_tokens=min(MAX_TOKENS, spec.max_output_tokens), temperature=0.0)
    except Unreachable as unreachable:
        # Never got an answer. That is about the network, or the provider's
        # edge, or this machine — not about the model, so it must not be
        # recorded as though the model had been tried and found wanting.
        return Measurement(model=spec.id, provider=spec.provider,
                           state=State.NOT_VERIFIED, at=stamp,
                           latency_ms=int((time.monotonic() - started) * 1000),
                           reason=str(unreachable)[:200])
    except LLMError as refused:
        # The provider answered and declined. That is a fact about the model or
        # the account, and the message already avoids carrying key material —
        # `_raise_for_status` is careful about that and this adds nothing.
        return Measurement(model=spec.id, provider=spec.provider,
                           state=State.REFUSED, at=stamp,
                           latency_ms=int((time.monotonic() - started) * 1000),
                           reason=str(refused)[:200])
    except Exception as failure:  # noqa: BLE001 - classified, never swallowed
        # The call did not complete. This says nothing about the model, so it
        # must not be recorded as though it did.
        return Measurement(model=spec.id, provider=spec.provider,
                           state=State.NOT_VERIFIED, at=stamp,
                           reason=f"the call did not complete: "
                                  f"{type(failure).__name__}")

    return Measurement(
        model=spec.id, provider=spec.provider, state=State.REACHED, at=stamp,
        latency_ms=completion.latency_ms or int((time.monotonic() - started) * 1000),
        input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
        cost_usd=completion.cost_usd, answered=(completion.text or "")[:120])


def run(registrations: Iterable[Any], store: Store, *,
        pause_seconds: float = 0.0) -> list[Measurement]:
    """Measure every registration, in order, recording each as it happens.

    Recorded one at a time rather than at the end: a run that dies halfway has
    still measured half, and throwing that away because the process stopped is
    how a slow provider costs a whole benchmark.

    `pause_seconds` exists because NVIDIA's edge blocks a burst by *address* —
    it answered `403 Forbidden` as an nginx page to every request, from every
    model, with a key that worked fine from elsewhere. A survey that gets the
    caller banned has surveyed nothing.
    """
    done: list[Measurement] = []
    for registration in registrations:
        if pause_seconds and done:
            time.sleep(pause_seconds)
        measurement = measure(registration.provider, registration.spec)
        store.record(measurement)
        done.append(measurement)
        log.info("benchmark: %s %s %sms", measurement.model,
                 measurement.state.value, measurement.latency_ms)
    return done


def summary(latest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Counts per state, and the fastest thing that answered.

    No "score" and no ranking beyond latency. Latency is a fact this measured;
    anything about quality would be an opinion formed from one trivial prompt.
    """
    counts = {state.value: 0 for state in State}
    for row in latest.values():
        counts[str(row.get("state", State.NOT_VERIFIED.value))] = (
            counts.get(str(row.get("state")), 0) + 1)

    reached = [r for r in latest.values() if r.get("state") == State.REACHED.value
               and r.get("latency_ms") is not None]
    fastest = min(reached, key=lambda r: r["latency_ms"], default=None)
    return {
        "counts": counts,
        "measured": len(latest),
        "fastest": {"model": fastest["model"], "latency_ms": fastest["latency_ms"]}
        if fastest else None,
        "note": ("Latency and cost are measured. Nothing here scores quality: "
                 "one trivial prompt cannot, and a number that looked like a "
                 "quality score would be believed."),
    }


__all__ = ["FILE", "Measurement", "State", "Store", "measure", "run", "summary"]
