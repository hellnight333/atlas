# Meta and WhatsApp Business Platform — preparation, deliberately not connected

**Status: nothing connected, no credential requested, no application started.**

## Why this is postponed rather than built

The offer has never been put in front of a business owner. Connecting the
WhatsApp Business Platform means a Meta Business Portfolio, business
verification against a trade licence, a dedicated phone number, a display-name
review and template approvals — days of process, before a single reply exists to
justify it.

The first five messages are sent **by hand, from Ayoub's phone**, on the number
prospects would reach anyway. That tests the offer at a cost of about twenty
minutes. The Platform only becomes worth its setup once messages need to go out
at a volume a person cannot type.

## What connecting it would require, in order

1. **Meta Business Portfolio** for *Asia Link Internet Content Provider LLC* —
   the legal entity, not "Qevik".
2. **Business verification**: trade licence, and a domain or utility document
   matching the entity name. `qevik.ai` is registered to the brand, not the
   entity — expect this mismatch to be queried.
3. **A dedicated phone number.** A number registered to WhatsApp Business
   Platform is consumed by it: the WhatsApp Business *app* on that number stops
   working, and migration is one-way in practice.
   **+971 50 102 9104 must not be used for this** — it is Ayoub's working number
   and is in the signature of every draft. A second SIM is required, and its
   number then becomes the sender identity prospects reply to.
4. **Display name review.** "Qevik" as a display name for an entity licensed as
   Asia Link will likely be rejected; the same naming problem as the Business
   Profile in `71_GOOGLE_SETUP.md`, and it should be resolved once for both.
5. **Message templates.** Any business-initiated message needs an approved
   template. Cold outreach templates are approved as **MARKETING**, which is the
   category most likely to be rate-limited or rejected, and the category
   recipients can block wholesale.
6. **Webhook** for delivery receipts and inbound replies. The architecture for
   this already exists in `atlas_kernel.outreach.channels` — shape only, no
   client — so adding a provider is a visible diff, not a config flag.
7. **Opt-out handling and consent logging** are not optional. Every inbound
   "STOP" must suppress the number permanently, and the suppression must be
   recorded as a `BusinessEvent` so it survives a rebuild.

## The constraint worth stating plainly

Cold outreach on WhatsApp is on thin ice regardless of how it is sent. Meta's
policy expects prior opt-in for business-initiated messages, and the enforcement
mechanism is recipients pressing *Block*. A handful of blocks against a
Platform number degrades quality rating and eventually messaging limits.

That is a further argument for the manual test: it produces the evidence for
whether this channel is worth formalising **before** anything is staked on it.

## Twilio

No advantage here. Twilio resells the same WhatsApp Platform and adds a layer of
cost and indirection over an identity Qevik still has to verify with Meta
directly. If a provider is ever chosen, go to Meta.
