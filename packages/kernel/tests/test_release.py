"""Release-engineering tests: version, licensing, telemetry, updates.

The telemetry tests are the important ones. They assert a privacy *guarantee*,
not an implementation detail, so they are written to fail if someone later
widens what is collected without meaning to.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas_kernel.api import app
from atlas_kernel.config import Profile, TelemetryMode, load_config
from atlas_kernel.telemetry import (
    ALLOWED_EVENT_FIELDS,
    FileSink,
    NullSink,
    TelemetryService,
    sanitise_traceback,
)
from atlas_kernel.updates import (
    Release,
    StaticFeed,
    UpdateService,
)
from atlas_kernel.version import (
    CHANNEL,
    LICENSE_ID,
    VERSION,
    parse_version,
    version_report,
)

client = TestClient(app)


# --------------------------------------------------------------------------
# Version
# --------------------------------------------------------------------------


def test_version_is_parseable_semver() -> None:
    parsed = parse_version(VERSION)
    assert (parsed.major, parsed.minor) == (0, 12)
    assert parsed.is_prerelease


@pytest.mark.parametrize(
    "lower,higher",
    [
        ("1.0.0", "1.0.1"),
        ("1.0.0", "1.1.0"),
        ("1.0.0", "2.0.0"),
        ("1.0.0-alpha.1", "1.0.0-alpha.2"),
        ("1.0.0-alpha.9", "1.0.0-alpha.10"),
        ("1.0.0-alpha.1", "1.0.0-beta.1"),
        # A full release outranks any pre-release of the same numbers.
        ("1.0.0-rc.1", "1.0.0"),
    ],
)
def test_version_ordering(lower: str, higher: str) -> None:
    assert parse_version(lower) < parse_version(higher)


def test_numeric_prerelease_parts_compare_numerically_not_lexically() -> None:
    # The bug this guards: "10" < "9" as strings, so alpha.10 would look older.
    assert parse_version("1.0.0-alpha.10") > parse_version("1.0.0-alpha.9")


def test_leading_v_is_tolerated_because_git_tags_have_one() -> None:
    assert parse_version("v0.12.0-alpha.1") == parse_version("0.12.0-alpha.1")


@pytest.mark.parametrize("bad", ["", "abc", "1.0", "1.0.0.0", "v", "1.x.0"])
def test_unparseable_versions_raise_rather_than_guess(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_version(bad)


def test_version_endpoint_reports_build_identity() -> None:
    body = client.get("/version").json()
    assert body["version"] == VERSION
    assert body["channel"] == CHANNEL
    assert body["is_prerelease"] is True
    assert body["license"] == LICENSE_ID


def test_version_report_never_omits_license_change_terms() -> None:
    report = version_report()
    assert report["license_change_to"] == "Apache-2.0"
    assert report["license_change_date"] == "2030-08-03"


# --------------------------------------------------------------------------
# Licensing
# --------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_license_file_exists_and_is_bsl() -> None:
    text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Business Source License 1.1" in text
    assert "Change Date:          2030-08-03" in text
    assert "Apache License, Version 2.0" in text


def test_notice_declares_the_copyleft_dependencies() -> None:
    """psycopg is LGPL and certifi is MPL. Shipping them silently is the risk."""
    notice = (REPO_ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "LGPL-3.0-only" in notice
    assert "psycopg" in notice
    assert "MPL-2.0" in notice
    assert "certifi" in notice
    assert "PostgreSQL License" in notice


def test_license_endpoint_does_not_claim_to_be_open_source() -> None:
    body = client.get("/license").json()
    assert body["license"] == "BUSL-1.1"
    assert body["source_available"] is True
    assert body["osi_approved"] is False


# --------------------------------------------------------------------------
# Telemetry — consent
# --------------------------------------------------------------------------


def test_telemetry_is_disabled_by_default() -> None:
    service = TelemetryService()
    assert service.enabled is False
    assert service.consent.mode is TelemetryMode.DISABLED
    assert service.consent.asked is False


@pytest.mark.parametrize("profile", list(Profile))
def test_no_profile_enables_telemetry(profile: Profile) -> None:
    """Consent belongs to a person, not to a deployment environment."""
    config = load_config({"ATLAS_PROFILE": profile.value})
    assert config.telemetry_mode is TelemetryMode.DISABLED
    assert config.update_check_enabled is False


def test_disabled_service_writes_nothing_at_all(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.jsonl"
    service = TelemetryService(sink=FileSink(path))

    assert service.record_version() is None
    assert service.record_usage("image", "ok") is None
    try:
        raise ValueError("boom")
    except ValueError as exc:
        assert service.record_crash(exc) is None

    assert not path.exists()


def test_consent_can_be_granted_at_runtime_and_takes_effect_immediately(
    tmp_path: Path,
) -> None:
    """Regression: opting in must not require a restart to do anything."""
    path = tmp_path / "telemetry.jsonl"
    service = TelemetryService(sink=FileSink(path))
    service.set_consent(TelemetryMode.DIAGNOSTICS)
    service.record_version()
    assert path.exists()
    assert len(path.read_text().splitlines()) == 1


def test_revoking_consent_destroys_the_install_id() -> None:
    service = TelemetryService()
    service.set_consent(TelemetryMode.DIAGNOSTICS)
    assert service.consent.install_id is not None

    service.set_consent(TelemetryMode.DISABLED)
    assert service.consent.install_id is None


def test_install_id_is_stable_while_consent_holds() -> None:
    service = TelemetryService()
    first = service.set_consent(TelemetryMode.CRASH_ONLY).install_id
    second = service.set_consent(TelemetryMode.DIAGNOSTICS).install_id
    assert first == second


def test_re_enabling_after_revocation_produces_a_new_identity() -> None:
    service = TelemetryService()
    first = service.set_consent(TelemetryMode.DIAGNOSTICS).install_id
    service.set_consent(TelemetryMode.DISABLED)
    second = service.set_consent(TelemetryMode.DIAGNOSTICS).install_id
    assert first != second


def test_crash_only_consent_does_not_collect_usage_or_version() -> None:
    service = TelemetryService()
    service.set_consent(TelemetryMode.CRASH_ONLY)
    assert service.record_version() is None
    assert service.record_usage("image", "ok") is None
    try:
        raise RuntimeError("x")
    except RuntimeError as exc:
        assert service.record_crash(exc) is not None


# --------------------------------------------------------------------------
# Telemetry — the privacy guarantee
# --------------------------------------------------------------------------

SECRETS = [
    "hunter2",
    "/Users/ayoub/Documents/private-project",
    "sk-ant-api03-REDACTED",
    "client-acquisition-strategy.docx",
]


def test_crash_report_never_contains_the_exception_message() -> None:
    service = TelemetryService()
    service.set_consent(TelemetryMode.CRASH_ONLY)
    try:
        raise ValueError(f"failed opening {SECRETS[1]} with key {SECRETS[2]}")
    except ValueError as exc:
        payload = service.record_crash(exc, component="assets")

    assert payload is not None
    blob = json.dumps(payload)
    for secret in SECRETS:
        assert secret not in blob
    assert payload["exception_type"] == "ValueError"


def test_traceback_sanitiser_drops_frames_outside_atlas() -> None:
    try:
        json.loads("{not json")
    except ValueError as exc:
        frames = sanitise_traceback(exc)
    # Every surviving frame is an Atlas module reference, never a file path.
    for frame in frames:
        assert re.fullmatch(r"[\w/]+:[\w<>]+:\d+", frame), frame
        assert "/Users" not in frame
        assert ".py" not in frame


def test_every_emitted_field_is_on_the_allow_list(tmp_path: Path) -> None:
    """The guarantee: a field cannot be collected until it is allow-listed."""
    path = tmp_path / "t.jsonl"
    service = TelemetryService(sink=FileSink(path))
    service.set_consent(TelemetryMode.DIAGNOSTICS)
    service.record_version()
    service.record_usage("image", "ok", duration_ms=12.345)
    try:
        raise KeyError("secret")
    except KeyError as exc:
        service.record_crash(exc, component="graph")

    lines = path.read_text().splitlines()
    assert len(lines) == 3
    for line in lines:
        assert set(json.loads(line)) <= ALLOWED_EVENT_FIELDS


def test_usage_recording_has_no_parameter_that_accepts_user_content() -> None:
    """record_usage takes a component and an outcome. There is no payload arg."""
    import inspect

    params = set(inspect.signature(TelemetryService.record_usage).parameters)
    assert params == {"self", "component", "outcome", "duration_ms", "now"}


def test_report_states_plainly_that_user_content_is_not_collected() -> None:
    report = TelemetryService().report()
    assert report["collects"]["user_content"] is False
    assert report["remote_endpoint"] is None


def test_file_sink_survives_an_unwritable_path(tmp_path: Path) -> None:
    """Telemetry must never take the application down with it."""
    sink = FileSink(tmp_path / "a-file" / "nested" / "t.jsonl")
    (tmp_path / "a-file").write_text("not a directory")
    sink.emit({"event": "version"})  # must not raise


def test_null_sink_accepts_and_discards() -> None:
    assert NullSink().emit({"event": "version"}) is None


# --------------------------------------------------------------------------
# Telemetry — API
# --------------------------------------------------------------------------


def test_telemetry_endpoint_round_trip() -> None:
    try:
        body = client.get("/telemetry").json()
        assert body["collects"]["user_content"] is False

        enabled = client.put("/telemetry/consent", json={"mode": "diagnostics"}).json()
        assert enabled["enabled"] is True
        assert enabled["consent"]["install_id"]

        revoked = client.put("/telemetry/consent", json={"mode": "disabled"}).json()
        assert revoked["enabled"] is False
        assert revoked["consent"]["install_id"] is None
    finally:
        # This client shares the composition-root service with other tests.
        client.put("/telemetry/consent", json={"mode": "disabled"})


def test_unknown_consent_mode_is_rejected() -> None:
    assert client.put("/telemetry/consent", json={"mode": "everything"}).status_code == 422


# --------------------------------------------------------------------------
# Updates
# --------------------------------------------------------------------------


def _release(version: str, prerelease: bool = False, assets: list[dict] | None = None) -> Release:
    return Release(
        version=version,
        name=f"Atlas {version}",
        url="https://example.invalid/release",
        prerelease=prerelease,
        assets=tuple(assets or []),
    )


def test_no_releases_means_no_update() -> None:
    result = UpdateService(feed=StaticFeed([]), current_version="0.12.0").check()
    assert result.update_available is False
    assert result.latest_version is None


def test_newer_release_is_detected() -> None:
    service = UpdateService(feed=StaticFeed([_release("0.13.0")]), current_version="0.12.0")
    result = service.check()
    assert result.update_available is True
    assert result.latest_version == "0.13.0"


def test_older_and_equal_releases_do_not_trigger_an_update() -> None:
    feed = StaticFeed([_release("0.11.0"), _release("0.12.0")])
    result = UpdateService(feed=feed, current_version="0.12.0").check()
    assert result.update_available is False
    assert result.latest_version == "0.12.0"


def test_stable_channel_ignores_prereleases() -> None:
    feed = StaticFeed([_release("0.13.0-alpha.1", prerelease=True)])
    result = UpdateService(feed=feed, current_version="0.12.0", channel="stable").check()
    assert result.update_available is False


def test_alpha_channel_sees_prereleases() -> None:
    feed = StaticFeed([_release("0.13.0-alpha.1", prerelease=True)])
    result = UpdateService(feed=feed, current_version="0.12.0", channel="alpha").check()
    assert result.update_available is True


def test_unparseable_tags_are_skipped_not_fatal() -> None:
    feed = StaticFeed([_release("nightly"), _release("0.13.0")])
    result = UpdateService(feed=feed, current_version="0.12.0").check()
    assert result.latest_version == "0.13.0"


def test_a_failing_feed_reports_an_error_instead_of_raising() -> None:
    class Broken:
        def fetch(self) -> list[Release]:
            raise ConnectionError("network is down")

    result = UpdateService(feed=Broken(), current_version="0.12.0").check()
    assert result.update_available is False
    assert result.error is not None and "network is down" in result.error


def test_an_unparseable_current_version_is_reported_not_crashed() -> None:
    result = UpdateService(feed=StaticFeed([_release("1.0.0")]), current_version="???").check()
    assert result.update_available is False
    assert result.error is not None


def test_update_result_always_declares_itself_optional() -> None:
    body = UpdateService(feed=StaticFeed([_release("9.9.9")]), current_version="0.12.0")
    payload = body.check().to_dict()
    assert payload["mandatory"] is False
    assert payload["auto_update"] is False


def test_download_url_is_matched_per_platform() -> None:
    assets = [
        {"name": "Atlas_0.13.0_x64-setup.exe", "browser_download_url": "https://x.invalid/win"},
        {"name": "Atlas_0.13.0_aarch64.dmg", "browser_download_url": "https://x.invalid/mac"},
    ]
    service = UpdateService(
        feed=StaticFeed([_release("0.13.0", assets=assets)]), current_version="0.12.0"
    )
    result = service.check()
    assert service.download_url_for("dmg", result) == "https://x.invalid/mac"
    assert service.download_url_for("setup.exe", result) == "https://x.invalid/win"
    assert service.download_url_for("AppImage", result) is None


def test_update_check_endpoint_makes_no_network_call_by_default() -> None:
    body = client.post("/updates/check").json()
    assert body["mandatory"] is False
    assert body["update_available"] is False
    assert body["error"] is None


def test_check_timestamp_is_recorded() -> None:
    stamp = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    result = UpdateService(feed=StaticFeed([]), current_version="0.12.0").check(now=stamp)
    assert result.checked_at == stamp.isoformat()
