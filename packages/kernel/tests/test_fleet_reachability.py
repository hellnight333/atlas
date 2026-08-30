"""Could a machine anywhere but the control-plane host join the fleet?

Measured on 2026-08-30: Postgres listened on 127.0.0.1 only and Tailscale was
not installed, so a fully provisioned Z8 with an approved Tailscale login had
nothing to connect to — while the provisioning actions were written as though a
tailnet existed.

The failure that matters is a false yes. Telling somebody the fleet is ready
when the first real worker cannot connect wastes a trip to a machine; saying
"undetermined" costs nothing.
"""

from __future__ import annotations

from atlas_kernel.controlplane.actions import fleet_reachability_actions
from atlas_kernel.fabric.reachability import DSN_VARIABLE, measure


class TestWhereTheLedgerLives:
    def test_a_loopback_ledger_cannot_be_reached_from_another_machine(self) -> None:
        found = measure("postgresql://user:secret@127.0.0.1:5432/qevik")

        assert found.reachable is False
        assert "loopback" in found.because

    def test_localhost_by_name_is_the_same_answer(self) -> None:
        """It reads as a hostname rather than an address and would otherwise
        fall through to "undetermined" — the one spelling most likely to be in
        a real DSN."""
        found = measure("postgresql://user:secret@localhost:5432/qevik")

        assert found.reachable is False

    def test_a_routable_address_is_not_reported_as_working(self) -> None:
        """It may be firewalled, or pg_hba may refuse the user. A false yes
        sends somebody to a machine that then cannot connect."""
        found = measure("postgresql://user:secret@100.64.1.5:5432/qevik")

        assert found.reachable is None
        assert "firewall" in found.because

    def test_a_hostname_is_not_resolved_here(self) -> None:
        """Resolving it would measure this host's resolver rather than the
        fleet's."""
        found = measure("postgresql://user:secret@db.internal:5432/qevik")

        assert found.reachable is None
        assert found.host == "db.internal"

    def test_an_unset_variable_is_undetermined_not_unreachable(self) -> None:
        found = measure("")

        assert found.reachable is None
        assert DSN_VARIABLE in found.because

    def test_it_never_reports_the_credentials(self) -> None:
        """The DSN carries a password and this ends up in an API response."""
        found = measure("postgresql://qevik:hunter2@127.0.0.1:5432/qevik")

        rendered = repr(found.summary())
        assert "hunter2" not in rendered
        assert "qevik:" not in rendered

    def test_it_opens_no_connection(self) -> None:
        """Structural: it answers from configuration, not by dialling. A check
        that connected would report this host's own access, which is the one
        machine whose access was never in question."""
        import ast
        import inspect

        from atlas_kernel.fabric import reachability

        # Imports and calls, not text. Matching text failed on this module's own
        # sentence explaining that whether a worker can *connect* depends on the
        # firewall — the same self-reference trap as the outreach guard.
        tree = ast.parse(inspect.getsource(reachability))

        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import) for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert not imported & {"socket", "psycopg", "psycopg2", "sqlalchemy"}, (
            f"the reachability check imports a network client: {imported}")

        called = {
            node.func.attr if isinstance(node.func, ast.Attribute)
            else getattr(node.func, "id", "")
            for node in ast.walk(tree) if isinstance(node, ast.Call)
        }
        assert not called & {"connect", "create_engine", "getaddrinfo",
                             "SessionLocal", "create_connection"}, (
            f"the reachability check dials something: {sorted(called)}")


class TestWhatTheOperatorIsAsked:
    def test_an_unreachable_ledger_produces_one_prerequisite_action(self) -> None:
        found = fleet_reachability_actions(False, tenant="t")

        assert len(found) == 1
        assert found[0].affects == ("fleet:remote-workers",)
        assert "a Tailscale login" in found[0].requires

    def test_it_does_not_claim_to_be_blocking(self) -> None:
        """Nothing today needs a second machine. The reason to do this is to
        make the workstations usable, not to unstick current work."""
        assert fleet_reachability_actions(False, tenant="t")[0].blocking is False

    def test_a_reachable_ledger_asks_for_nothing(self) -> None:
        assert fleet_reachability_actions(True, tenant="t") == ()

    def test_an_undetermined_answer_asks_for_nothing(self) -> None:
        """Asking somebody to open a database to the network because a check
        failed is worse than saying nothing."""
        assert fleet_reachability_actions(None, tenant="t") == ()

    def test_it_says_not_to_expose_the_database_publicly(self) -> None:
        """The instruction is the dangerous part. Someone following "make
        Postgres reachable" without this sentence opens 5432 to the internet."""
        action = fleet_reachability_actions(False, tenant="t")[0]

        assert "Do not expose 5432 to the public internet" in action.instructions

    def test_the_machine_actions_point_at_this_prerequisite(self) -> None:
        """Otherwise somebody provisions a Z8, joins a tailnet, and discovers at
        the last step that there was never anything to connect to."""
        from atlas_kernel.controlplane.actions import node_actions

        for action in node_actions((), tenant="t"):
            assert "cannot reach the ledger" in action.instructions
