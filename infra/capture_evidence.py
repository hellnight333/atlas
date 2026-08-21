#!/usr/bin/env python3
"""Photograph each prospect's homepage, so a sales claim can be looked at.

A finding that says "no Arabic version" is a sentence somebody has to trust. A
screenshot of the homepage taken at a stated time, at a stated viewport, is the
same claim with its evidence attached — and it is the difference between a
dashboard that asserts things and one that shows them.

Both viewports are captured because they answer different questions. Desktop is
what the owner believes their site looks like; 390x844 is what their customers
actually see, and the gap between the two is frequently the whole pitch.

Three rules:

- **Never invent an image.** A site that will not load produces no file and a
  recorded reason. The dashboard shows "screenshot not captured", which is true,
  rather than a placeholder that reads as evidence.
- **Never overwrite.** Files are named by capture time, so a re-verification
  adds a second observation instead of erasing the first. The whole point of
  keeping evidence is to be able to show that something changed.
- **The event is the record, not the file.** A `screenshot_captured`
  BusinessEvent carries the URL, viewport, HTTP status, load time and path, so
  the timeline remains the source of truth and a lost file degrades to a
  missing image rather than a missing fact.

    capture_evidence.py --top 40
    capture_evidence.py --name Malabar
    capture_evidence.py --all-scored
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_kernel.browser import PlaywrightSession  # noqa: E402
from atlas_kernel.opportunity.models import BusinessEvent  # noqa: E402
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402

from score_prospects import load, scored  # noqa: E402

EVIDENCE = Path("/var/lib/qevik/evidence")

#: What the owner thinks it looks like, and what their customer sees.
VIEWPORTS = {"desktop": (1280, 900), "mobile": (390, 844)}

#: Wide enough to read in a card, small enough that a list of forty does not
#: cost forty full-size images.
THUMB_WIDTH = 420


def thumbnail(png: bytes) -> bytes:
    from PIL import Image

    image = Image.open(io.BytesIO(png))
    height = round(image.height * THUMB_WIDTH / image.width)
    small = image.convert("RGB").resize((THUMB_WIDTH, height), Image.LANCZOS)
    out = io.BytesIO()
    small.save(out, format="JPEG", quality=78, optimize=True)
    return out.getvalue()


def capture(session: PlaywrightSession, url: str, target: Path):
    """Status, milliseconds, error. Never raises for a dead site.

    Goes through `session.screenshot` rather than reaching for the underlying
    page. The session drives Chromium on a dedicated thread and every public
    method hops onto it; calling Playwright directly from here would work until
    it deadlocked.
    """
    started = time.monotonic()
    try:
        page = session.open(url)
        session.screenshot(target, full_page=False)
        return page.status, int((time.monotonic() - started) * 1000), ""
    except Exception as error:  # noqa: BLE001 - a dead site must not end the run
        return 0, int((time.monotonic() - started) * 1000), str(error).split("\n")[0][:140]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--all-scored", action="store_true")
    parser.add_argument("--skip-existing", action="store_true",
                        help="leave businesses that already have a capture alone")
    args = parser.parse_args(argv)

    candidates = {c["id"]: c for c in load()}
    ranked = scored(load())
    if args.name:
        wanted = [n.lower() for n in args.name]
        targets = [s for s in ranked if any(w in s.name.lower() for w in wanted)]
    elif args.all_scored:
        targets = ranked
    else:
        targets = ranked[: args.top]

    repo = OpportunityRepository()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    done = missing = 0
    stamp = datetime.now(UTC)
    results: dict[str, dict] = {}

    # One viewport at a time, one browser at a time. The viewport is fixed at
    # session construction, and this host caps concurrent Chromium at two for
    # reasons that were learned the hard way.
    for label, viewport in VIEWPORTS.items():
        session = PlaywrightSession(headless=True, viewport=viewport).start()
        try:
            for index, score in enumerate(targets, 1):
                business = candidates[score.business_id]
                folder = EVIDENCE / score.business_id
                if args.skip_existing and folder.exists() and any(folder.glob(f"{label}-*.png")):
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                name = f"{label}-{stamp:%Y%m%dT%H%M%S}"
                target = folder / f"{name}.png"

                status, elapsed, error = capture(session, business["website"], target)
                shot = results.setdefault(score.business_id, {"url": business["website"], "shots": {}})
                if not target.exists() or not target.stat().st_size:
                    missing += 1
                    target.unlink(missing_ok=True)
                    shot["shots"][label] = {"captured": False, "reason": error or "no response",
                                            "http_status": status, "load_ms": elapsed}
                    continue
                png = target.read_bytes()
                (folder / f"{name}.thumb.jpg").write_bytes(thumbnail(png))
                shot["shots"][label] = {
                    "captured": True, "file": f"{name}.png", "thumb": f"{name}.thumb.jpg",
                    "viewport": f"{viewport[0]}x{viewport[1]}", "http_status": status,
                    "load_ms": elapsed, "bytes": len(png),
                }
                done += 1
                if index % 10 == 0 or index == len(targets):
                    print(f"  {label:<8} {index:>3}/{len(targets)}  captured {done}  missing {missing}")
        finally:
            session.close()

    # One event per business, carrying both viewports.
    for business_id, record in results.items():
        repo.record_event(BusinessEvent(
            business_id=business_id, factory="website",
            kind="screenshot_captured", actor="capture_evidence.py",
            detail={"url": record["url"], "captured_at": stamp.isoformat(),
                    "shots": record["shots"]},
        ))

    print(f"\ncaptured : {done} images")
    print(f"missing  : {missing} (recorded as not captured, never faked)")
    print(f"stored   : {EVIDENCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
