from atlas_kernel.event_bus import (
    DEFAULT_EVENT_TYPES,
    EventBus,
    EventRegistry,
    JobStarted,
)


def test_event_bus_publish_subscribe():
    bus = EventBus()
    received: list[JobStarted] = []

    def handler(event: JobStarted) -> None:
        received.append(event)

    bus.subscribe(JobStarted, handler)
    bus.publish(JobStarted(job_id="job-123", run_id="run-123", action="image.generate"))

    assert len(received) == 1
    assert received[0].run_id == "run-123"
    assert received[0].job_id == "job-123"
    assert received[0].action == "image.generate"


def test_event_bus_publish_without_subscribers_is_safe():
    bus = EventBus()
    bus.publish(JobStarted(job_id="job-1", run_id="run-1", action="text.generate"))


def test_event_registry_contains_default_event_types():
    registry = EventRegistry()
    names = {event_type.__name__ for event_type in registry.list()}
    for event_type in DEFAULT_EVENT_TYPES:
        assert event_type.__name__ in names
