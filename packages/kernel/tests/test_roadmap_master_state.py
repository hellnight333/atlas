"""The roadmap page, and the payload nobody had built.

`views.roadmap` fetched `/control/roadmap` and expected `product_a`,
`product_b` and `product_c`. No such route existed, and `MASTER_STATE.md` — the
document the page's own comment names as the source — has no such sections. So
the page 404'd on every load and rendered an apology, which was the right
refusal for the wrong reason: it said a hardcoded copy would create a second
answer to "what is built" that drifts from the first, and inventing three
product bands the source does not contain is the same mistake.

These tests are mostly about that: the reader quotes, and never composes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from atlas_kernel.qevik import Wiring, create_app
from atlas_kernel.roadmap import master_state


@pytest.fixture
def client(tmp_path):
    app = create_app(Wiring(repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json"))
    with TestClient(app) as test_client:
        yield test_client


class TestItReadsTheRealDocument:
    def test_the_document_this_repository_ships_is_the_one_parsed(self) -> None:
        """Not a fixture that agrees with the parser."""
        assert master_state.MASTER_STATE.is_file(), master_state.MASTER_STATE
        report = master_state.read()
        assert report["known"] is True
        assert report["reconciled_at"], "the document states a reconciliation date"

    def test_every_named_section_is_present_in_the_document(self) -> None:
        """A heading renamed in the document takes a band of work off the
        screen. Reported as missing rather than skipped, and asserted here so
        the rename is noticed at the rename rather than by an operator."""
        missing = [s["title"] for s in master_state.read()["sections"]
                   if s["missing"]]
        assert missing == [], (
            f"MASTER_STATE.md no longer has: {missing}. Either restore the "
            "heading or update roadmap.master_state.SECTIONS.")

    def test_a_capability_table_arrives_as_rows_keyed_by_its_own_header(self) -> None:
        """Keyed by the document's own column names, so renaming a column
        renames it here rather than silently filling a key nobody updated."""
        operational = next(s for s in master_state.read()["sections"]
                           if s["title"] == "Operational now")
        assert operational["rows"], "the table did not parse"
        assert set(operational["rows"][0]) == {"Capability", "Evidence"}

    def test_a_three_column_table_keeps_its_third_column(self) -> None:
        components = next(s for s in master_state.read()["sections"]
                          if s["title"].startswith("Roadmap components"))
        assert components["rows"]
        assert "Status" in components["rows"][0]

    def test_prose_sections_arrive_as_paragraphs_not_as_wrapped_lines(self) -> None:
        """The document is hard-wrapped. One line per line would be unreadable
        and would also be a different text from the one that was written."""
        blocked = next(s for s in master_state.read()["sections"]
                       if s["title"] == "Blocked, precisely")
        assert blocked["prose"]
        assert any(len(p) > 120 for p in blocked["prose"]), (
            "paragraphs were not rejoined across the document's wrapping")

    def test_the_table_is_not_repeated_in_the_prose(self) -> None:
        operational = next(s for s in master_state.read()["sections"]
                           if s["title"] == "Operational now")
        assert not any("|" in p for p in operational["prose"])


class TestItDerivesNothing:
    def test_the_reader_computes_no_status_of_its_own(self) -> None:
        """Everything on that page is a quotation. A roadmap surface that
        decided for itself whether something was done would be a second answer
        to the question the document exists to answer."""
        import ast
        import inspect

        # The parsed module, with docstrings dropped: the prose here describes
        # what this reader refuses to do and would otherwise trip a word-list —
        # a guard that fails on its own explanation teaches people to weaken it.
        def undocumented(node):
            """Strip the docstring wherever one may appear, then recurse."""
            body = getattr(node, "body", None)
            if isinstance(body, list):
                node.body = [n for n in body
                             if not (isinstance(n, ast.Expr)
                                     and isinstance(n.value, ast.Constant)
                                     and isinstance(n.value.value, str))]
                for child in node.body:
                    undocumented(child)
            return node

        code = ast.unparse(undocumented(ast.parse(inspect.getsource(master_state))))

        for forbidden in ("score", "complete", "percent", "progress",
                          "datetime", "requests.", "httpx", "SessionLocal"):
            assert forbidden not in code, (
                f"the roadmap reader does more than quote: {forbidden}")

    def test_an_unreadable_document_is_not_an_empty_roadmap(self, tmp_path) -> None:
        report = master_state.read(tmp_path / "not-here.md")
        assert report["known"] is False
        assert "not the same as the roadmap being empty" in report["detail"]
        assert report["sections"] == []


class TestTheRoute:
    def test_the_roadmap_route_exists_at_all(self, client) -> None:
        """It did not, for as long as the page existed to call it."""
        assert client.get("/control/roadmap").status_code == 200

    def test_it_is_not_public(self, tmp_path) -> None:
        """It quotes an internal document naming modules, blockers and open
        product decisions."""
        app = create_app(Wiring(repository_root=tmp_path,
                                vault_path=tmp_path / "vault.json"))
        from atlas_kernel.auth.api import CONSOLE_PATHS, PUBLIC_PATHS

        assert "/control/roadmap" not in PUBLIC_PATHS
        assert "/control/roadmap" not in CONSOLE_PATHS
        assert app is not None

    def test_the_console_asks_for_what_the_route_returns(self) -> None:
        """The failure this whole module exists to close: a page written
        against a payload nobody had built."""
        from pathlib import Path

        console = (Path(__file__).resolve().parents[3] / "apps" / "control" /
                   "src" / "index.html").read_text(encoding="utf-8")
        page = console.split("views.roadmap", 1)[1].split("views.missions", 1)[0]

        assert "data.sections" in page, "the page does not read the payload's sections"
        for invented in ("product_a", "product_b", "product_c"):
            assert invented not in page, (
                f"the page still expects {invented}, which nothing serves")


def test_the_deploy_ships_the_document_the_reader_looks_for() -> None:
    """The route existed on the host and the document did not.

    `MASTER_STATE.md` is at the repository root, which is not one of the three
    subtrees `deploy_control.sh` ships, so `/control/roadmap` answered "could
    not be read" on a perfectly healthy deployment — honest, and useless. The
    same shape as /office: a surface whose data was never copied.

    A fallback nobody checks is how two locations become one bug, so this
    asserts the deploy's move and the reader's candidate list are the same
    place.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    script = (root / "infra" / "deploy_control.sh").read_text(encoding="utf-8")

    exported = script.split('git -C "$ROOT" archive', 1)[1][:400]
    assert "$ROADMAP_PATH" in exported, (
        "the export does not include MASTER_STATE.md, so nothing reaches the host")
    assert 'cat-file -e "$SHA:MASTER_STATE.md"' in script, (
        "whether to ship it is not asked of the commit, so a commit that "
        "predates the document would fail to export at all")

    # After the export verification, never before: that check counts files
    # against the commit's own listing, and a file moved into a shipped subtree
    # early is one more than the commit has.
    verified = script.index('echo "export verified:')
    moved = script.index('mv "$EXPORT/MASTER_STATE.md"')
    assert verified < moved, (
        "the document is moved into a shipped subtree before the export is "
        "verified, so every deploy refuses with an off-by-one file count")

    destination = script.split('mv "$EXPORT/MASTER_STATE.md" "$EXPORT/', 1)[1
                               ].split('"', 1)[0]
    assert destination == "infra/MASTER_STATE.md", destination

    relative = [c for c in master_state.CANDIDATES
                if c != master_state.CANDIDATES[0]]
    assert relative, "the reader looks in only one place and the deploy moves it"
    assert relative[0].parent.name == "infra", (
        f"the deploy puts it in {destination} and the reader looks in "
        f"{relative[0].parent.name}/")


def test_the_reader_resolves_per_call_not_once_at_import() -> None:
    """A process that starts before the payload lands would otherwise cache
    "absent" for its whole life."""
    import inspect

    source = inspect.getsource(master_state.read)
    assert "_document()" in source, (
        "read() uses the module-level constant, so the answer is fixed at "
        "import time")
