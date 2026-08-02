from atlas_kernel.composition_root import create_runtime


def test_composition_root_shares_one_event_bus_across_major_components():
    runtime = create_runtime()

    assert runtime.orchestrator.bus is runtime.event_bus
    assert runtime.worker.bus is runtime.event_bus
    assert runtime.executor.bus is runtime.event_bus
    assert runtime.asset_service.bus is runtime.event_bus
    assert runtime.workflow_engine.bus is runtime.event_bus
