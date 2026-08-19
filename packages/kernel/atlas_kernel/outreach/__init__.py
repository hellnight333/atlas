"""Outreach: who is writing, and where messages will eventually go.

Deliberately split. `identity` is the letterhead — one place, so a signature
cannot drift and Qevik is never written as a company it is not. `channels` is
the seam email and WhatsApp will attach to, defined in full and connected to
nothing, so that gaining the ability to message twenty real businesses is a
reviewable diff rather than a flag flip.
"""

from .channels import (
    Channel,
    ChannelNotConnected,
    EmailChannel,
    NotApproved,
    NotReachable,
    OutreachError,
    SendResult,
    WhatsAppChannel,
    connected,
    registry,
)
from .experiment import (
    FACTORY as EXPERIMENT_FACTORY,
)
from .experiment import (
    Response,
    Result,
    Stage,
    fold,
    message_version,
    record_meeting,
    record_objection,
    record_outcome,
    record_prepared,
    record_price,
    record_response,
    record_sent,
)
from .identity import (
    ADDRESS_LINE_1,
    ADDRESS_LINE_2,
    BRAND,
    BRAND_LINE,
    EMAIL_SIGNATURE,
    LEGAL_ENTITY,
    NAME,
    PHONE,
    WHATSAPP_SIGNATURE,
    entity_claims,
)

__all__ = [
    "ADDRESS_LINE_1",
    "EXPERIMENT_FACTORY",
    "Response",
    "Result",
    "Stage",
    "fold",
    "message_version",
    "record_meeting",
    "record_objection",
    "record_outcome",
    "record_prepared",
    "record_price",
    "record_response",
    "record_sent",
    "ADDRESS_LINE_2",
    "BRAND",
    "BRAND_LINE",
    "Channel",
    "ChannelNotConnected",
    "EMAIL_SIGNATURE",
    "EmailChannel",
    "LEGAL_ENTITY",
    "NAME",
    "NotApproved",
    "NotReachable",
    "OutreachError",
    "PHONE",
    "SendResult",
    "WHATSAPP_SIGNATURE",
    "WhatsAppChannel",
    "connected",
    "entity_claims",
    "registry",
]
