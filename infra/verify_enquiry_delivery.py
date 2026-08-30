#!/usr/bin/env python3
"""Proves the inbound half of M1: a published page offers a contact path that
actually delivers, and offers none where it cannot.

The defect this closes was not a form that discarded submissions -- both
verticals were honest, each showing a notice that the backend did not exist.
It was that `website/enquiry.py` already built a *working* mailto + WhatsApp
block and was reached only by `execution.capabilities.enquiry`. Two
implementations of contact, and the published pages used the weaker one.

No endpoint, no database, no SMTP: the message is composed in the visitor's own
mail client or WhatsApp, and nothing can be dropped by us in between.

Run:  python3 infra/verify_enquiry_delivery.py
"""
from __future__ import annotations

import re
import sys

sys.path.insert(0, "packages/kernel")

from atlas_kernel.website import enquiry
from atlas_kernel.website.verticals import business as biz_vertical
from atlas_kernel.website.verticals import dental

PASSED: list[str] = []
FAILED: list[str] = []

MOBILE = "0501234567"      # WhatsApp can deliver here
LANDLINE = "043558808"     # it cannot


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))


def a_business(**over):
    fields = dict(name="Acme Services", schema_type="LocalBusiness",
                  tagline=biz_vertical.Text("t", "ت"),
                  intro=biz_vertical.Text("i", "إ"))
    fields.update(over)
    return biz_vertical.Business(**fields)


print("\n-- the dead controls are gone ------------------------------------------")
page = dental.render(name="Dr Joy", phone=MOBILE, email="hello@drjoy.ae")
check("the dental appointment form is no longer rendered",
      "appointment-form" not in page)
check("...nor its 'backend does not exist' notice",
      "form-notice" not in page and 'class="notice' not in page)
shop = biz_vertical.render(a_business(phone=MOBILE, email="hi@acme.ae"))
check("the business request form is no longer rendered", "request-form" not in shop)
check("...nor its notice element", 'id="rf-notice"' not in shop)

print("\n-- both channels, when the business has both ---------------------------")
for label, page in (("dental", dental.render(name="Dr Joy", phone=MOBILE,
                                             email="hello@drjoy.ae")),
                    ("business", biz_vertical.render(
                        a_business(phone=MOBILE, email="hi@acme.ae")))):
    check(f"{label}: a mailto link to the business address",
          "mailto:hello%40drjoy.ae" in page or "mailto:hi%40acme.ae" in page)
    check(f"{label}: a WhatsApp link to the mobile",
          f"wa.me/{MOBILE.lstrip('0')}" in page or f"wa.me/{MOBILE}" in page,
          re.search(r"wa\.me/\d+", page).group(0) if "wa.me/" in page else "none")
    check(f"{label}: the note says where the message goes",
          "your own email app" in page or "nothing is sent through this page" in page)

print("\n-- only the channel that can deliver -----------------------------------")
def enquiry_block(page: str) -> str:
    """Just the enquiry form, so a WhatsApp link elsewhere on the page cannot
    make this check pass or fail for the wrong reason."""
    start = page.find('class="enquiry"')
    return page[start:page.find("</form>", start)] if start >= 0 else ""


landline_email = dental.render(name="Dr Joy", phone=LANDLINE, email="hello@drjoy.ae")
block = enquiry_block(landline_email)
check("a landline gets a mailto and NO WhatsApp button",
      "mailto:" in block and "wa.me/" not in block,
      "a WhatsApp message to a landline is silence, not an error")
check("NEGATIVE CONTROL: a mobile does get the WhatsApp button",
      "wa.me/" in enquiry_block(
          dental.render(name="Dr Joy", phone=MOBILE, email="hello@drjoy.ae")),
      "so the absence above is the landline, not a broken block")
mobile_only = dental.render(name="Dr Joy", phone=MOBILE)
check("a mobile with no email gets WhatsApp and no mailto",
      "wa.me/" in mobile_only and "mailto:" not in mobile_only)

print("\n-- nothing to deliver to, so nothing is offered ------------------------")
nothing = dental.render(name="Dr Joy", phone=LANDLINE)
check("dental: no email and no mobile renders no enquiry form",
      'class="enquiry"' not in nothing,
      "a form with no destination is the defect this avoids")
check("...and the page is still useful — the phone link remains",
      f"tel:{LANDLINE}" in nothing or "tel:" in nothing)
none_biz = biz_vertical.render(a_business(phone=LANDLINE))
check("business: same", 'class="enquiry"' not in none_biz)

print("\n-- Arabic ---------------------------------------------------------------")
ar = dental.render(name="Dr Joy", phone=MOBILE, email="hello@drjoy.ae", lang="ar")
check("the Arabic page renders the Arabic enquiry block",
      "أرسل استفسارًا" in ar, "authored, not machine-substituted")
check("...and still links the same address", "mailto:hello%40drjoy.ae" in ar)

print("\n-- the block is styled where it is used --------------------------------")
for label, page in (("dental", dental.render(name="D", phone=MOBILE, email="h@d.ae")),
                    ("business", biz_vertical.render(
                        a_business(phone=MOBILE, email="h@a.ae")))):
    missing = [c for c in (".enquiry-actions", ".enquiry-send", ".enquiry-note")
               if c not in page]
    check(f"{label}: every enquiry class the block emits is styled",
          not missing, str(missing) if missing else "no unstyled control")

print("\n-- no server was introduced --------------------------------------------")
source = (open("packages/kernel/atlas_kernel/website/verticals/dental.py").read()
          + open("packages/kernel/atlas_kernel/website/verticals/business.py").read())
# `import x`, not the bare word: "requests" is a substring of "request", which
# appears throughout these templates as the id of a page section.
for forbidden in ("smtplib", "requests", "httpx", "fastapi", "sqlalchemy"):
    check(f"the verticals import no {forbidden}",
          f"import {forbidden}" not in source)
check("...and define no route", "@router" not in source and "APIRouter" not in source)
check("NEGATIVE CONTROL: the scan would catch one",
      "import html" in source, "it finds the imports that are there")
page = dental.render(name="D", phone=MOBILE, email="h@d.ae")
check("the rendered page posts nowhere",
      'action="' not in page and "fetch(" not in page and "XMLHttpRequest" not in page,
      "the visitor's own client delivers it; there is nothing of ours in between")
check("NEGATIVE CONTROL: it does contain the links that do the work",
      "mailto:" in page and "wa.me/" in page)

print("\n-- the upgrade path is still costed, not forgotten ---------------------")
gap = enquiry.hosted_form_gap()
check("a hosted form remains PENDING_INFRASTRUCTURE",
      gap["status"] == "PENDING_INFRASTRUCTURE")
check("...and still names spam handling and the retention decision",
      any("Spam" in n["item"] or "spam" in n["item"] for n in gap["needs"])
      and any("retention" in n["item"] for n in gap["needs"]),
      f"{len(gap['needs'])} dependencies, deferred rather than solved")

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
print("\nNOT PROOF OF DELIVERY. Production evidence still required: a real "
      "published site, and a real enquiry reaching the business owner.")
sys.exit(1 if FAILED else 0)
