"""The mission record itself, and the round trip it has to survive."""

from __future__ import annotations

def test_summary_carries_every_field_rehydrate_would_read():
    """`summary()` is written by hand and `rehydrate` derives from the model, so
    a new field lands in one and not the other unless something checks.

    The failure is quiet and expensive: the mission round-trips through the
    timeline losing whatever was added last, and the loss only shows up as a
    delivery that has forgotten which opportunity approved it.
    """
    from atlas_kernel.mission.models import Mission

    written = set(Mission(id="m", tenant_id="t", title="x").summary())
    # `id` is `mission_id` in the summary and `total_cost` is derived.
    expected = set(Mission.model_fields) - {"id"}
    missing = sorted(expected - written)
    assert not missing, (
        f"summary() does not carry {', '.join(missing)}; rehydrate reads every "
        "model field, so these would be dropped on the round trip")
