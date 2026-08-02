from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_ROOT = REPO_ROOT / "docs"
README = REPO_ROOT / "README.md"


MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
ADR_RE = re.compile(r"ADR-\d{4}-[A-Za-z0-9-]+\.md")


REQUIRED_DOCS = [
    DOCS_ROOT / "ARCHITECTURE.md",
    DOCS_ROOT / "CAPABILITY_LAYER.md",
    DOCS_ROOT / "COMPOSITION_ROOT.md",
    DOCS_ROOT / "EVENT_BUS.md",
    DOCS_ROOT / "EXECUTION_POLICY.md",
    DOCS_ROOT / "EXECUTOR_LAYER.md",
    DOCS_ROOT / "PLATFORM_STATUS.md",
    DOCS_ROOT / "WORKFLOW_ENGINE.md",
    DOCS_ROOT / "DEVELOPER_GUIDE.md",
    DOCS_ROOT / "CI.md",
    DOCS_ROOT / "TESTING.md",
    DOCS_ROOT / "Domain_Glossary.md",
    DOCS_ROOT / "decisions" / "ADR-0005-Asset-System.md",
    DOCS_ROOT / "decisions" / "ADR-0006-Workflow-Engine.md",
    DOCS_ROOT / "decisions" / "ADR-0007-Capability-Layer.md",
    DOCS_ROOT / "decisions" / "ADR-0008-Execution-Policy.md",
]


def _iter_markdown_files() -> list[Path]:
    return [README] + sorted(path for path in DOCS_ROOT.rglob("*.md") if path.is_file())


def test_required_documents_exist():
    missing = [str(path.relative_to(REPO_ROOT)) for path in REQUIRED_DOCS if not path.exists()]

    assert not missing, f"Missing required docs: {missing}"


def test_internal_markdown_links_resolve():
    broken: list[str] = []
    for path in _iter_markdown_files():
        content = path.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK_RE.findall(content):
            if (
                target.startswith("http://")
                or target.startswith("https://")
                or target.startswith("#")
            ):
                continue
            normalized = target.split("#", 1)[0]
            resolved = (path.parent / normalized).resolve()
            if not resolved.exists():
                broken.append(f"{path.relative_to(REPO_ROOT)} -> {target}")

    assert not broken, "Broken internal links:\n" + "\n".join(broken)


def test_adr_references_point_to_existing_files():
    referenced = set()
    for path in _iter_markdown_files():
        content = path.read_text(encoding="utf-8")
        referenced.update(ADR_RE.findall(content))

    missing = [name for name in sorted(referenced) if not (DOCS_ROOT / "decisions" / name).exists()]
    assert not missing, f"Missing ADR files referenced by docs: {missing}"
