"""The founding-client offer, and what to say when a prospect pushes on it.

Price lives here rather than in the message templates because it must **not**
appear in a first contact. A number in an opening message turns a conversation
about their website into a negotiation before they have looked at anything, and
the demo is the argument — the price is the answer to a question they have not
asked yet.

The replies below are short on purpose. A long answer to "not interested" reads
as an attempt to argue someone out of a decision they already made, and the only
thing it reliably buys is a blocked number.

Every claim in them is one the audit supports or the demo demonstrates. Nothing
here promises booking, ranking, traffic or a timeline.
"""

from __future__ import annotations

from typing import Final

from .identity import BRAND, LEGAL_ENTITY, NAME

SETUP_AED: Final = 1500
MONTHLY_AED: Final = 199
CURRENCY: Final = "AED"

#: One line, for a record or a report. Never for an opening message.
PRICE_LINE: Final = f"{CURRENCY} {SETUP_AED:,} setup + {CURRENCY} {MONTHLY_AED}/month"

#: The rule the templates enforce.
PRICE_IN_FIRST_MESSAGE: Final = False


def price_reply() -> str:
    """Used only when they ask. Plain number, no framing, no discount."""
    return (
        f"It's {CURRENCY} {SETUP_AED:,} to set up, then {CURRENCY} {MONTHLY_AED} a month "
        "for hosting and keeping it updated.\n\n"
        "That covers the English and Arabic pages you can already see on the demo, "
        "your details kept correct, and changes when you need them.\n\n"
        "The appointment form is a placeholder today — it doesn't submit anywhere. "
        "If you want real online booking, that's a separate conversation once we "
        "pick a provider."
    )


def send_details_reply(demo_url: str) -> str:
    """They asked for more. Give the thing, not a brochure."""
    return (
        "Of course. The example is here, and it's live — open it on your phone:\n"
        f"{demo_url}\n\n"
        f"Add /ar/ to the end for the Arabic version.\n\n"
        "Everything on it comes from your own Google listing — name, number, "
        "address and opening hours. I haven't invented any doctors, insurers or "
        "reviews.\n\n"
        "Happy to walk through it on a call if that's easier."
    )


def not_interested_reply() -> str:
    """Accept it. One line, and leave the door open without pushing on it."""
    return (
        "Understood — thanks for taking a look. The example stays up, so keep the "
        "link in case it's useful later. All the best."
    )


def who_is_qevik_reply() -> str:
    """The honest answer, including that Qevik is not its own company."""
    return (
        f"{BRAND} is what I call the website work I do for clinics here in Dubai. "
        f"It runs under my company, {LEGAL_ENTITY}, based in Deiram.\n\n"
        f"It's me — {NAME}. I'm not an agency and there's no call centre. I build "
        "the site, you deal with me directly.\n\n"
        "The example I sent is the actual work, not a mock-up — it's live on the "
        "internet right now."
    )


def playbook(demo_url: str) -> dict[str, str]:
    """Everything to have on screen while the conversation is happening."""
    return {
        "they ask the price": price_reply(),
        "they say send details": send_details_reply(demo_url),
        "they say not interested": not_interested_reply(),
        "they ask who or what Qevik is": who_is_qevik_reply(),
    }
