"""How strong a claim the evidence actually supports — and therefore how it may
be worded.

The brief asks for a phrase gate but warns against relying on a blacklist. So
the language is not policed separately: **each attribution level owns the verbs
it licenses**, and a sentence is checked against the level its own evidence
earned. A blacklist can be worked around by rephrasing; this cannot, because the
rephrasing does not change what the data supports.

The levels, and exactly what each requires:

``UNKNOWN``
    Something needed is missing — no baseline, no observation, or no defined
    window. Nothing may be said about change at all. This is the default, and a
    measurement that cannot climb out of it is still a useful, honest record.

``OBSERVED``
    A baseline, an observation, and a window they both sit inside. Licenses a
    statement of fact about the numbers: *organic leads went from 34 to 61
    during the window.* It licenses no connection to anything Qevik did.

``ASSOCIATED``
    Everything OBSERVED requires, plus an intervention that happened **before**
    the observation window opened. Licenses temporal language: *an increase was
    observed after the intervention.* Still not a cause — the ordering is
    necessary for causation and nowhere near sufficient.

``ATTRIBUTED``
    Everything ASSOCIATED requires, plus a source that independently ties the
    change to the intervention — a referrer, a landing page, a campaign
    parameter, a channel breakdown. Licenses *the change is attributed to the
    intervention*, with the source named.

No level licenses *"Qevik increased X"*. That sentence claims sole agency over
somebody else's business result, and no measurement this system can take
establishes it. It is unreachable by design rather than by omission.
"""

from __future__ import annotations

import re
from enum import StrEnum


class Attribution(StrEnum):
    UNKNOWN = "UNKNOWN"
    OBSERVED = "OBSERVED"
    ASSOCIATED = "ASSOCIATED"
    ATTRIBUTED = "ATTRIBUTED"


#: Ascending strength. Index is the comparison.
ORDER: tuple[Attribution, ...] = (Attribution.UNKNOWN, Attribution.OBSERVED,
                                  Attribution.ASSOCIATED, Attribution.ATTRIBUTED)


def at_least(level: Attribution, floor: Attribution) -> bool:
    return ORDER.index(level) >= ORDER.index(floor)


class Claim(StrEnum):
    """What a sentence is asserting, independent of how it is phrased."""

    #: "no change could be established"
    NOTHING = "nothing"
    #: "X went from A to B during the window"
    CHANGE = "change"
    #: "the change was observed after the intervention"
    SEQUENCE = "sequence"
    #: "the change is attributed to the intervention, per <source>"
    ATTRIBUTION = "attribution"
    #: "Qevik increased X" — sole agency over the customer's result
    AGENCY = "agency"


#: The strongest claim each level licenses.
LICENSES: dict[Attribution, Claim] = {
    Attribution.UNKNOWN: Claim.NOTHING,
    Attribution.OBSERVED: Claim.CHANGE,
    Attribution.ASSOCIATED: Claim.SEQUENCE,
    Attribution.ATTRIBUTED: Claim.ATTRIBUTION,
}

_CLAIM_ORDER: tuple[Claim, ...] = (Claim.NOTHING, Claim.CHANGE, Claim.SEQUENCE,
                                   Claim.ATTRIBUTION, Claim.AGENCY)

#: Phrases that assert sole agency. Not the gate — the gate is the level — but
#: these identify the claim a sentence is making so it can be compared to it.
_AGENCY = re.compile(
    r"\b(qevik (increased|caused|improved|grew|drove|delivered|boosted)"
    r"|because of qevik|thanks to qevik|we increased|we caused|we grew"
    r"|(this|the campaign|the intervention|it) (caused|generated|resulted in|drove)"
    # A promise is an agency claim in the future tense, and it is the form a
    # roadmap naturally reaches for — "this will drive more leads" asserts
    # exactly what "this drove more leads" does, before any evidence exists.
    r"|(will|would|should|is going to) (increase|drive|generate|boost|grow"
    r"|improve|deliver|bring|lift|raise|double|convert)"
    r"|responsible for the (increase|growth|improvement))\b", re.I)
_ATTRIBUTION = re.compile(
    # "because of Qevik" was covered and bare "because of" was not, so the same
    # causal claim passed whenever it credited something other than us.
    r"\b(attributed to|driven by|came from|sourced from|via the .*campaign"
    r"|referred by|because of|due to the|as a result of|thanks to"
    r"|(grew|rose|fell|dropped|improved) because)\b", re.I)
_SEQUENCE = re.compile(
    r"\b(after the (intervention|change|work|launch)|following the"
    r"|since the (intervention|change)|subsequent to)\b", re.I)
_CHANGE = re.compile(
    r"\b(increased from|decreased from|went from|rose from|fell from|changed from"
    r"|measured|observed|during the (measurement )?window)\b", re.I)


def claim_of(sentence: str) -> Claim:
    """The strongest thing this sentence asserts.

    Order matters: a sentence containing both an agency phrase and a hedge is
    still making the agency claim, and reading it the other way is how a
    disclaimer launders an unsupported statement.
    """
    text = sentence or ""
    if _AGENCY.search(text):
        return Claim.AGENCY
    if _ATTRIBUTION.search(text):
        return Claim.ATTRIBUTION
    if _SEQUENCE.search(text):
        return Claim.SEQUENCE
    if _CHANGE.search(text):
        return Claim.CHANGE
    return Claim.NOTHING


def permits(level: Attribution, sentence: str) -> bool:
    """Whether the evidence behind `level` supports what `sentence` asserts."""
    return _CLAIM_ORDER.index(claim_of(sentence)) <= _CLAIM_ORDER.index(LICENSES[level])


def refuse(level: Attribution, sentence: str) -> str:
    """Empty when the sentence is supported, otherwise why it is not."""
    made = claim_of(sentence)
    if permits(level, sentence):
        return ""
    if made is Claim.AGENCY:
        return ("claims Qevik caused the result. No measurement this system takes "
                "establishes sole agency over a customer's business outcome, so no "
                "attribution level licenses it.")
    return (f"asserts {made.value!r} but the evidence supports only "
            f"{LICENSES[level].value!r} ({level.value}).")


def phrasing(level: Attribution, *, metric: str, before, after, window: str,
             source: str = "") -> str:
    """A sentence this level actually licenses. Used instead of hand-writing one."""
    if level is Attribution.UNKNOWN:
        return f"{metric}: no change could be established."
    movement = f"{metric} went from {before} to {after} during {window}"
    if level is Attribution.OBSERVED:
        return f"{movement}."
    if level is Attribution.ASSOCIATED:
        return f"{movement}, after the intervention."
    named = f", per {source}" if source else ""
    return f"{movement}, and the change is attributed to the intervention{named}."
