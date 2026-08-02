from atlas_kernel.asset_system import AssetService
from atlas_kernel.event_bus import AssetCreated, EventBus
from atlas_kernel.models import Asset
from atlas_kernel.repository import AtlasRepository
from atlas_kernel.storage import PassthroughStorageBackend


def test_asset_service_creates_and_publishes_asset():
    repository = AtlasRepository()
    bus = EventBus()
    service = AssetService(repository, bus, PassthroughStorageBackend())
    emitted: list[AssetCreated] = []

    def handler(event: AssetCreated) -> None:
        emitted.append(event)

    bus.subscribe(AssetCreated, handler)

    asset = service.create_asset(
        Asset(
            id="asset-test",
            run_id="run-test",
            job_id="job-test",
            type="image",
            uri="https://example.com/test.png",
            metadata={"tag": "demo"},
        )
    )

    assert asset.id == "asset-test"
    assert asset.type == "image"
    assert asset.uri == "https://example.com/test.png"
    assert emitted[0].asset_id == "asset-test"
    assert emitted[0].run_id == "run-test"
    assert emitted[0].job_id == "job-test"
