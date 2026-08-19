"""Who is writing, stated once.

Every draft signs off with the same name, number and legal entity, and none of
them assemble it themselves. A signature composed per-message is one that drifts
— and the part most likely to drift is the part that must not.

**Qevik is a brand, not a company.** It is operated by Asia Link Internet Content
Provider LLC. Writing "Qevik LLC", "Qevik FZ-LLC", or anything implying Qevik
holds its own UAE trade licence is a false statement about a regulated status to
a business that will check. `FORBIDDEN_ENTITY_CLAIMS` exists so that mistake is
caught by a test rather than by a prospect's lawyer.
"""

from __future__ import annotations

import re
from typing import Final

NAME: Final = "Ayoub Soleimani"
PHONE: Final = "+971 50 102 9104"

#: The licensed company. Qevik is its product.
LEGAL_ENTITY: Final = "Asia Link Internet Content Provider LLC"
BRAND: Final = "Qevik"

#: How the brand and the entity are written together. Never one without the
#: other in an email footer.
BRAND_LINE: Final = f"{BRAND} — by {LEGAL_ENTITY}"

ADDRESS_LINE_1: Final = "Office 301, Al Othman Building"
ADDRESS_LINE_2: Final = "Deiram, Dubai, UAE"

EMAIL_SIGNATURE: Final = "\n".join(
    (NAME, BRAND_LINE, ADDRESS_LINE_1, ADDRESS_LINE_2, PHONE)
)

#: Shorter, because a WhatsApp message carrying a postal address reads as a
#: mail-merge rather than a person.
WHATSAPP_SIGNATURE: Final = "\n".join((NAME, BRAND, PHONE))

#: Phrasings that assert Qevik is separately licensed. Checked against every
#: draft before it is written.
FORBIDDEN_ENTITY_CLAIMS: Final = (
    re.compile(r"\bqevik\s+(llc|l\.l\.c|fz-?llc|fze|ltd|limited|inc|dmcc|fzco)\b", re.I),
    re.compile(r"\bqevik\s+is\s+(a|an)\s+(licen[cs]ed|registered|uae|dubai)\b", re.I),
    re.compile(r"\bqevik'?s?\s+(trade\s+licen[cs]e|commercial\s+licen[cs]e)\b", re.I),
    re.compile(r"\bregistered\s+(as|under)\s+qevik\b", re.I),
)


def entity_claims(text: str) -> list[str]:
    """Any phrasing that would present Qevik as its own legal entity."""
    return [
        match.group(0)
        for pattern in FORBIDDEN_ENTITY_CLAIMS
        if (match := pattern.search(text))
    ]
