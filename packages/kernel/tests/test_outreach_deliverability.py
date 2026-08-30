"""Whether the domain can send mail anybody accepts — and, above all, whether
this can tell "no record" apart from "no answer".

The failure that matters is not a wrong verdict, it is a confident one. A
resolver that times out looks exactly like a domain with no SPF, and reporting
the second would send somebody to Cloudflare to create a record that is already
there, or conclude the domain is unprotected when it is fine.
"""

from __future__ import annotations

import subprocess

import pytest

from atlas_kernel.outreach import deliverability
from atlas_kernel.outreach.deliverability import State, measure


def _answers(monkeypatch, table: dict[tuple[str, str], object]) -> None:
    """Drive `_dig` from a table. A missing key means "answered, nothing there";
    an explicit `None` means the resolver did not answer."""
    monkeypatch.setattr(deliverability, "_dig",
                        lambda name, kind, **_: table.get((name, kind), ()))


class TestTellingAbsenceFromSilence:
    def test_a_resolver_that_does_not_answer_is_never_reported_as_absent(
            self, monkeypatch) -> None:
        monkeypatch.setattr(deliverability, "_dig", lambda *a, **k: None)

        found = measure("qevik.ai")

        assert found.unreadable is True
        assert found.missing == (), "silence was reported as a missing record"
        assert set(found.unmeasured) == {"MX", "SPF", "DMARC", "DKIM"}
        assert found.ready_to_send is False, "unknown must never read as ready"

    def test_a_domain_with_no_records_is_reported_as_absent(
            self, monkeypatch) -> None:
        """The negative control for the test above: when the resolver *does*
        answer and there is nothing there, that is a finding."""
        _answers(monkeypatch, {})

        found = measure("qevik.ai")

        assert found.unreadable is False
        assert set(found.missing) == {"MX", "SPF", "DMARC", "DKIM"}
        assert found.unmeasured == ()

    def test_one_unanswered_question_does_not_make_the_rest_unknown(
            self, monkeypatch) -> None:
        _answers(monkeypatch, {
            ("qevik.ai", "MX"): None,
            ("qevik.ai", "TXT"): ("v=spf1 include:_spf.google.com ~all",),
        })

        found = measure("qevik.ai")

        assert found.unmeasured == ("MX",)
        assert "SPF" not in found.missing
        assert found.can_receive_a_reply is False, (
            "an unmeasured MX must not read as a working one")


class TestWhatTheRecordsMean:
    def test_spf_is_matched_on_content_not_on_any_txt_record(
            self, monkeypatch) -> None:
        """A domain has TXT records for all sorts of things. Treating any TXT as
        an SPF record reports every verified domain as protected."""
        _answers(monkeypatch, {
            ("qevik.ai", "TXT"): ("google-site-verification=abc123", "MS=ms12345"),
        })

        assert "SPF" in measure("qevik.ai").missing

    def test_dmarc_is_read_from_its_own_name(self, monkeypatch) -> None:
        _answers(monkeypatch, {
            ("_dmarc.qevik.ai", "TXT"): ("v=DMARC1; p=quarantine; rua=mailto:a@b",),
        })

        found = measure("qevik.ai")

        assert "DMARC" not in found.missing
        assert found.state_of("DMARC") is State.PRESENT

    def test_ready_to_send_needs_a_reply_path_as_well_as_authentication(
            self, monkeypatch) -> None:
        """SPF and DMARC without an MX means mail is accepted and the reply
        bounces. That is not ready."""
        _answers(monkeypatch, {
            ("qevik.ai", "TXT"): ("v=spf1 include:_spf.google.com ~all",),
            ("_dmarc.qevik.ai", "TXT"): ("v=DMARC1; p=none",),
        })

        found = measure("qevik.ai")

        assert found.ready_to_send is False
        assert found.can_receive_a_reply is False

    def test_a_fully_configured_domain_reads_as_ready(self, monkeypatch) -> None:
        _answers(monkeypatch, {
            ("qevik.ai", "MX"): ("1 smtp.google.com.",),
            ("qevik.ai", "TXT"): ("v=spf1 include:_spf.google.com ~all",),
            ("_dmarc.qevik.ai", "TXT"): ("v=DMARC1; p=quarantine",),
            ("google._domainkey.qevik.ai", "TXT"): ("v=DKIM1; k=rsa; p=MIIB",),
        })

        found = measure("qevik.ai")

        assert found.ready_to_send is True
        assert found.can_receive_a_reply is True
        assert found.missing == ()

    def test_dkim_absence_does_not_hold_sending_shut(self, monkeypatch) -> None:
        """A provider may sign under a selector nobody named. Demanding proof
        the method cannot obtain would block on a record that is probably fine,
        so DKIM is reported and not required."""
        _answers(monkeypatch, {
            ("qevik.ai", "MX"): ("1 smtp.google.com.",),
            ("qevik.ai", "TXT"): ("v=spf1 include:_spf.google.com ~all",),
            ("_dmarc.qevik.ai", "TXT"): ("v=DMARC1; p=quarantine",),
        })

        found = measure("qevik.ai")

        assert "DKIM" in found.missing
        assert found.ready_to_send is True

    def test_it_says_dkim_absence_is_evidence_and_not_proof(
            self, monkeypatch) -> None:
        _answers(monkeypatch, {})

        dkim = next(r for r in measure("qevik.ai").records if r.name == "DKIM")

        assert "cannot be found by" in dkim.detail

    def test_every_record_says_why_it_matters(self, monkeypatch) -> None:
        """An operator asked to create a DNS record deserves the consequence,
        not the protocol name."""
        _answers(monkeypatch, {})

        for record in measure("qevik.ai").records:
            assert len(record.matters_because) > 40, record.name


class TestItReadsAndNothingElse:
    def test_dig_reports_silence_when_the_command_fails(self, monkeypatch) -> None:
        """Exit code, not empty output."""
        monkeypatch.setattr(deliverability.shutil, "which", lambda _: "/usr/bin/dig")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k:
                            subprocess.CompletedProcess(a, 9, stdout="", stderr=""))

        assert deliverability._dig("qevik.ai", "MX") is None

    def test_dig_reports_absence_when_it_succeeds_with_no_answer(
            self, monkeypatch) -> None:
        """`dig` exits zero with no output for a name that truly has no record.
        The negative control for the test above."""
        monkeypatch.setattr(deliverability.shutil, "which", lambda _: "/usr/bin/dig")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k:
                            subprocess.CompletedProcess(a, 0, stdout="", stderr=""))

        assert deliverability._dig("qevik.ai", "MX") == ()

    def test_a_diagnostic_line_is_not_an_answer(self, monkeypatch) -> None:
        """dig prints ';; connection timed out' on stdout and still exits zero.
        Read as an answer, that becomes an MX record named ';;'."""
        monkeypatch.setattr(deliverability.shutil, "which", lambda _: "/usr/bin/dig")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k:
                            subprocess.CompletedProcess(
                                a, 0, stdout=";; connection timed out\n", stderr=""))

        assert deliverability._dig("qevik.ai", "MX") is None

    def test_no_dig_on_the_box_is_silence_not_absence(self, monkeypatch) -> None:
        monkeypatch.setattr(deliverability.shutil, "which", lambda _: None)

        assert deliverability._dig("qevik.ai", "MX") is None
        assert measure("qevik.ai").unreadable is True

    def test_it_takes_no_recipient_and_cannot_send(self) -> None:
        """Structural. This asks about our own domain; a recipient parameter
        would make it something that can be pointed at a business."""
        import ast
        import inspect

        # The *code*, not the prose. Matching raw text failed on this module's
        # own docstring explaining that it takes no recipient — the same trap
        # the console's localStorage guard documents.
        tree = ast.parse(inspect.getsource(deliverability))
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                node.value.value = ""          # blank every docstring
        source = ast.unparse(tree)

        for forbidden in ("smtplib", "recipient", "sendmail", "httpx", "requests"):
            assert forbidden not in source, (
                f"the deliverability check references {forbidden!r}; it reads "
                "public DNS about our own domain and must not grow a way to "
                "contact anybody")
        assert list(inspect.signature(measure).parameters) == ["domain"]

    def test_it_is_not_the_module_that_says_who_signs(self) -> None:
        """`outreach.identity` is who is writing. Keeping them apart stops a
        DNS check acquiring an opinion about the signature, and vice versa."""
        from atlas_kernel.outreach import identity

        assert identity.BRAND == "Qevik"
        assert not hasattr(deliverability, "EMAIL_SIGNATURE")


@pytest.mark.parametrize("domain", ["qevik.ai", "example.test"])
def test_measuring_a_domain_with_no_resolver_never_raises(
        monkeypatch, domain) -> None:
    """It runs inside an action-centre read. An exception here would take out
    the page that tells the operator what to do about it."""
    monkeypatch.setattr(deliverability.shutil, "which", lambda _: None)

    assert measure(domain).unreadable is True
