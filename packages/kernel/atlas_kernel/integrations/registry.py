"""Every external system Qevik can talk to, and whether it can talk to it yet.

A missing API key is an ordinary state during development, not a failure and not
a reason to stop. What makes it ordinary is that it is *represented*: the system
knows which provider is unconfigured, which capability that blocks, and exactly
what a person would have to do about it. Without that, "it does not work" and
"nobody has connected it" look identical from the outside.

So this is a catalogue, not a mechanism. It holds no credentials — the
credential itself is a `publication.Connection`, which stores a *reference* to a
secret and never the secret — and it performs no network calls. Its whole job is
to answer, per provider:

    what it is · what it is for · what credential it needs · where to get one ·
    whether this tenant has one · which capabilities are blocked without it

The status is **derived** from whether the tenant actually holds a connection.
A stored status field would be a second answer to a question the connection
store already answers, and it would go stale the moment somebody connected an
account.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..opportunity.tenancy import TenantId
from ..publication.connections import ConnectionStore
from ..publication.models import ConnectionKind


def _root_exists(variable: str) -> bool:
    """Whether a filesystem-backed integration actually has somewhere to write.

    Resolved the way the publisher resolves it — the environment variable if set,
    otherwise the documented default — and then checked for real, because the
    question is whether publication can happen rather than whether somebody typed
    a setting.

    Checking only the variable was wrong in exactly the way this whole entry was
    wrong: production has never set `QEVIK_SITES_ROOT`, publishes to the default
    `/srv/sites`, and would have kept reporting "connect me" while serving live
    customer sites out of that directory.
    """
    from ..mission.toolrunner import DEFAULT_SITES_ROOT, SITES_ROOT_ENV

    if variable != SITES_ROOT_ENV:                 # pragma: no cover - one today
        return bool(os.environ.get(variable, "").strip())
    root = os.environ.get(SITES_ROOT_ENV, DEFAULT_SITES_ROOT).strip()
    return bool(root) and Path(root).is_dir()


class IntegrationStatus(StrEnum):
    """Derived, never stored."""

    #: A credential exists for this tenant and this provider.
    CONNECTED = "connected"
    #: Nobody has supplied the credential. Not an error.
    PENDING_CREDENTIAL = "pending_credential"
    #: Deliberately not wired. Distinct from pending, because "we have not
    #: built this" and "you have not connected this" are different sentences
    #: and only one of them is the customer's move.
    NOT_IMPLEMENTED = "not_implemented"


class Category(StrEnum):
    """What a connector is *for*, in the terms a person browsing them uses.

    A flat list of forty is a wall; the same forty under seven headings is a
    directory. Grouped by the job to be done rather than by vendor or protocol,
    because nobody opens a connector list looking for "the OAuth ones".
    """

    MODEL = "model"            #: The models that think, see, speak or draw.
    MESSAGING = "messaging"    #: Reaching one person: email, SMS, chat.
    SOCIAL = "social"          #: Reaching an audience, under a name.
    COMMERCE = "commerce"      #: Selling: marketplaces and payments.
    ANALYTICS = "analytics"    #: Finding out what happened.
    INFRASTRUCTURE = "infrastructure"  #: Where things are stored and served.
    WORKSPACE = "workspace"    #: The tools a team already works in.


class Integration(BaseModel):
    """One external system, described for whoever has to connect it."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    #: Why Qevik wants it, in the customer's terms rather than ours.
    purpose: str
    kind: ConnectionKind
    #: What to add. The *name* of the thing, never a value.
    credential: str
    #: Where a person goes to get one.
    setup_url: str = ""
    #: Capability or measurement ids that cannot run without it. Named so the
    #: consequence of not connecting is visible next to the request.
    blocks: tuple[str, ...] = ()
    #: Which shelf of the catalogue it sits on.
    category: Category = Category.INFRASTRUCTURE
    #: What connecting it lets the customer *do*, in one sentence of their
    #: language. `blocks` names capability ids, which are ours; a person
    #: deciding whether to go and find a token needs the other sentence.
    unlocks: str = ""
    #: False when the adapter itself is not built yet.
    adapter_ready: bool = True
    #: How a person knows they are finished, in the terms of the actual check.
    #:
    #: Empty means the ordinary test: a connection exists for this tenant. Some
    #: integrations need more, and saying otherwise tells somebody they are done
    #: when they are not — `smtp` needs five settings before `EmailChannel`
    #: reports itself configured, and a filesystem root is a directory that has
    #: to exist rather than a credential anybody stores.
    verification: str = ""

    def verifies_by(self) -> str:
        return self.verification or (
            f"a connection to {self.id} exists for this tenant")

    def status(self, store: ConnectionStore, *, tenant: TenantId | None
               ) -> IntegrationStatus:
        if not self.adapter_ready:
            return IntegrationStatus.NOT_IMPLEMENTED
        if store.for_target(self.id, tenant=tenant) is not None:
            return IntegrationStatus.CONNECTED
        # A filesystem-backed integration is connected when it actually has
        # somewhere to write. That is not a per-tenant secret somebody stores
        # through the Credential Centre — it is how the deployment was
        # installed, and `_root_exists` resolves it exactly as the publisher
        # does rather than asking whether a variable was typed.
        #
        # Without this, the action centre listed "Connect Local filesystem —
        # blocks publication" on a deployment that had been publishing to that
        # very directory for weeks. One wrong item is how a human action list
        # stops being read, which costs more than the item was worth.
        if self.kind is ConnectionKind.FILESYSTEM:
            return (IntegrationStatus.CONNECTED if _root_exists(self.credential)
                    else IntegrationStatus.PENDING_CREDENTIAL)
        return IntegrationStatus.PENDING_CREDENTIAL

    def describe(self, store: ConnectionStore, *, tenant: TenantId | None) -> dict:
        """Safe to show a customer. Contains no secret because none is held."""
        state = self.status(store, tenant=tenant)
        connection = (store.for_target(self.id, tenant=tenant)
                      if state is IntegrationStatus.CONNECTED else None)
        return {
            "provider": self.id, "name": self.name, "purpose": self.purpose,
            "status": state.value, "credential": self.credential,
            "setup_url": self.setup_url, "blocks": list(self.blocks),
            # The connection's id, never its reference and never its value.
            "connection_id": connection.id if connection else "",
            "action": ("connected" if connection
                       else f"Add {self.credential}" if state is
                       IntegrationStatus.PENDING_CREDENTIAL
                       else "not built yet"),
        }


#: The catalogue. Every entry names a capability that genuinely wants it — an
#: integration nothing consumes is a credential request nobody can justify.
INTEGRATIONS: tuple[Integration, ...] = (
    # --- the coding agents -------------------------------------------------
    # Listed here so a model provider is configured the same way as any other
    # external system, through the Credential Center, rather than through an
    # environment variable that dies with the shell that set it.
    Integration(
        id="qwen", category=Category.MODEL, name="Qwen (DashScope)",
        purpose="Run planning, implementation and review agents.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_DASHSCOPE_API_KEY",
        setup_url="https://dashscope.console.aliyun.com/",
        blocks=("agent:planning", "agent:implementation", "agent:review")),
    Integration(
        id="anthropic", category=Category.MODEL, name="Claude (Anthropic)",
        purpose="Run agents on the strongest available reasoning model.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_ANTHROPIC_API_KEY",
        setup_url="https://console.anthropic.com/settings/keys",
        blocks=("agent:planning", "agent:implementation", "agent:review")),
    Integration(
        id="openai", category=Category.MODEL, name="OpenAI / Codex",
        purpose="Run agents on an OpenAI-compatible model.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_OPENAI_API_KEY",
        setup_url="https://platform.openai.com/api-keys",
        blocks=("agent:implementation",)),
    Integration(
        id="nvidia", category=Category.MODEL, name="NVIDIA (build.nvidia.com)",
        purpose=("Run reasoning, coding, vision and embedding models on "
                 "NVIDIA's hosted inference — one key, many model families."),
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_NVIDIA_API_KEY",
        setup_url="https://build.nvidia.com/",
        blocks=("agent:planning", "agent:implementation", "agent:review",
                "agent:research")),
    Integration(
        id="deepseek", category=Category.MODEL, name="DeepSeek",
        purpose="Run cheaper background and summarisation work.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_DEEPSEEK_API_KEY",
        setup_url="https://platform.deepseek.com/api_keys",
        blocks=("agent:cheap", "agent:summarisation"),
        # No adapter is wired for it yet, so it reports NOT_IMPLEMENTED rather
        # than asking somebody for a key nothing could use.
        adapter_ready=False),
    Integration(
        id="stripe", category=Category.COMMERCE, name="Stripe",
        purpose="Take payment for plans, once billing exists.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_STRIPE_SECRET_KEY",
        setup_url="https://dashboard.stripe.com/apikeys",
        blocks=("billing",),
        # Billing is deliberately unbuilt; asking for a live payment key before
        # anything can use it is how a key sits unused in a store for a year.
        adapter_ready=False),
    Integration(
        id="smtp", category=Category.MESSAGING, name="Email (SMTP)",
        purpose="Send approved outreach and customer notifications.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_SMTP_PASSWORD",
        blocks=("outreach:send", "notifications"),
        verification=("all five of QEVIK_SMTP_HOST, _PORT, _USER, _PASSWORD and "
                      "_FROM are present, so `EmailChannel.configured()` is true. "
                      "Sending is proven only by a message arriving in a real "
                      "inbox with SPF, DKIM and DMARC passing in its headers"),
        # Built at M1: `outreach.channels.EmailChannel` sends through smtplib,
        # behind the approval boundary. The credential id is unchanged -- the
        # entry was extended rather than replaced, so nothing that already
        # referred to `smtp` has to learn a second name.
        #
        # `adapter_ready` says the adapter exists. It does not say a credential
        # is present, and it must never be read as "email works": the settings
        # named in `outreach.channels.SMTP_SETTINGS` are what decide that, and
        # only a delivered message proves it.
        adapter_ready=True),
    # Real code, cost-capped, and until now absent from this catalogue — so the
    # action centre could not ask for the one key that turns discovery from
    # "2-17% of OpenStreetMap businesses are contactable" into a workable
    # prospect list. `infra/market_scan.py` is configured for it and the
    # `qevik-market-scan` unit is dead without it.
    Integration(
        id="google-places", category=Category.ANALYTICS, name="Google Places",
        purpose=("Find real businesses with a phone and a website. OpenStreetMap "
                 "knows 2-17% of them are contactable; Places knows nearly all."),
        kind=ConnectionKind.API_TOKEN,
        credential="QEVIK_GOOGLE_PLACES_API_KEY",
        setup_url="https://console.cloud.google.com/apis/credentials",
        blocks=("discovery:contactable",),
        verification=("QEVIK_GOOGLE_PLACES_API_KEY is present and the "
                      "`qevik-market-scan` unit completes a scan returning "
                      "businesses with a phone or a website"),
        adapter_ready=True),
    # --- everything else ---------------------------------------------------
    Integration(
        id="local", category=Category.INFRASTRUCTURE, name="Local filesystem",
        purpose="Publish a site to a directory a web server serves.",
        kind=ConnectionKind.FILESYSTEM, credential="QEVIK_SITES_ROOT",
        blocks=("publication",),
        verification=("the sites root resolves to a directory that exists — the "
                      "variable if set, otherwise the deployment default")),
    Integration(
        id="ai-visibility", category=Category.ANALYTICS, name="AI search visibility",
        purpose="Find out whether AI assistants mention and cite this business.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_AI_VISIBILITY_TOKEN",
        blocks=("measurement:ai_mention_rate", "measurement:ai_citation_rate")),
    Integration(
        id="search-console", category=Category.ANALYTICS, name="Google Search Console",
        purpose="Read impressions, clicks and position for this domain.",
        kind=ConnectionKind.OAUTH, credential="QEVIK_SEARCH_CONSOLE_REFRESH_TOKEN",
        setup_url="https://search.google.com/search-console",
        blocks=("measurement:clicks", "measurement:impressions")),
    Integration(
        id="analytics", category=Category.ANALYTICS, name="Web analytics",
        purpose="Read sessions and conversion rate, so work can be measured.",
        kind=ConnectionKind.OAUTH, credential="QEVIK_ANALYTICS_REFRESH_TOKEN",
        blocks=("measurement:sessions", "measurement:conversion_rate")),
    Integration(
        id="cloudflare", category=Category.INFRASTRUCTURE, name="Cloudflare Pages",
        purpose="Publish a site to a real host rather than a local directory.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_CLOUDFLARE_API_TOKEN",
        setup_url="https://dash.cloudflare.com/profile/api-tokens",
        # The adapter exists as far as it can: domain verification, the upload
        # manifest, and refusals naming exactly what is needed. Only the HTTP
        # call is missing, and it is deliberately unwritten rather than written
        # blind against an API nobody here can run — see publication/targets.py.
        blocks=("publication:cloudflare",),
        adapter_ready=False),
    Integration(
        id="cloudflare-account", category=Category.INFRASTRUCTURE, name="Cloudflare account id",
        purpose="Names which Cloudflare account a site is published under.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_CLOUDFLARE_ACCOUNT_ID",
        setup_url="https://dash.cloudflare.com",
        # Not a secret, and registered here anyway: it is a value only the
        # account holder has, and a person entering a token needs to be asked
        # for it in the same place at the same time rather than discovering it
        # is missing at the first publish.
        blocks=("publication:cloudflare",),
        adapter_ready=False),
    # --- marketplaces ------------------------------------------------------
    #
    # Registered with `adapter_ready=False`, which is the honest state and not a
    # placeholder: the abstractions exist and the live calls do not, so these
    # appear in the Credential Centre as NOT_IMPLEMENTED rather than as a
    # request for a key. Asking a seller for Selling Partner credentials before
    # anything could use them is how a live marketplace token sits in a store
    # for a year — and a marketplace token can create orders.
    Integration(
        id="amazon", category=Category.COMMERCE, name="Amazon Selling Partner",
        purpose="List products and read orders and inventory from Amazon.",
        kind=ConnectionKind.OAUTH, credential="QEVIK_AMAZON_REFRESH_TOKEN",
        setup_url="https://sellercentral.amazon.com",
        blocks=("marketplace:amazon:listing", "marketplace:amazon:inventory",
                "marketplace:amazon:orders"),
        adapter_ready=False),
    Integration(
        id="noon", category=Category.COMMERCE, name="Noon Seller Lab",
        purpose="List products and read orders and inventory from Noon.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_NOON_API_KEY",
        setup_url="https://sellerlab.noon.com",
        blocks=("marketplace:noon:listing", "marketplace:noon:inventory",
                "marketplace:noon:orders"),
        adapter_ready=False),
    # --- social ------------------------------------------------------------
    #
    # Every one of these can publish to an audience under the customer's name.
    # They stay `adapter_ready=False` until there is an approval gate in front
    # of them, because the failure mode is not a broken feature — it is a post
    # nobody agreed to, on somebody else's account, which cannot be recalled.
    Integration(
        id="youtube", category=Category.SOCIAL, name="YouTube",
        purpose="Publish approved video to the customer's channel.",
        kind=ConnectionKind.OAUTH, credential="QEVIK_YOUTUBE_REFRESH_TOKEN",
        setup_url="https://console.cloud.google.com/apis/credentials",
        blocks=("social:youtube:publish", "measurement:youtube_views"),
        adapter_ready=False),
    Integration(
        id="instagram", category=Category.SOCIAL, name="Instagram",
        purpose="Publish approved posts to the customer's account.",
        kind=ConnectionKind.OAUTH, credential="QEVIK_INSTAGRAM_ACCESS_TOKEN",
        setup_url="https://developers.facebook.com/apps",
        blocks=("social:instagram:publish", "measurement:instagram_reach"),
        adapter_ready=False),
    # --- generation --------------------------------------------------------
    #
    # One token, many models. Replicate hosts Flux for stills and Wan, Kling and
    # Hailuo for video behind a single asynchronous job API, so the choice of
    # model lives in a versioned recipe rather than in a code branch — and a new
    # model is a recipe change, not an integration.
    #
    # `adapter_ready=True`: `media/providers/replicate.py` submits, polls and
    # fetches for real. It is the first provider in this system that generates
    # anything; everything before it was a mock at the bottom of a complete
    # assembly, provenance and publish chain.
    Integration(
        id="replicate", category=Category.MODEL, name="Replicate",
        purpose="Run image and video models — Flux, Wan, Kling and others — through one API.",
        unlocks="Generate images and video from a prompt, in the recipes Qevik ships.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_REPLICATE_API_TOKEN",
        setup_url="https://replicate.com/account/api-tokens",
        blocks=("media:image:generate", "media:video:generate"),
        adapter_ready=True),
    Integration(
        id="fal", category=Category.MODEL, name="fal.ai",
        purpose="A second generation host, for models Replicate does not carry and as a fallback.",
        unlocks="Keeps image and video generation working when one host is down or a model moves.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_FAL_API_KEY",
        setup_url="https://fal.ai/dashboard/keys",
        blocks=("media:image:generate", "media:video:generate"),
        adapter_ready=False),
    Integration(
        id="elevenlabs", category=Category.MODEL, name="ElevenLabs",
        purpose="Speak a script in a chosen voice, in the languages a customer sells in.",
        unlocks="Narration for video, and a consistent voice across every clip a brand publishes.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_ELEVENLABS_API_KEY",
        setup_url="https://elevenlabs.io/app/settings/api-keys",
        blocks=("media:audio:narrate",),
        adapter_ready=False),
    # --- messaging ---------------------------------------------------------
    #
    # Every entry here reaches one identifiable person. They stay
    # `adapter_ready=False` until the approval gate is in front of them, because
    # the failure is not a broken feature — it is a message to a real person
    # that nobody agreed to send, and it cannot be recalled.
    Integration(
        id="twilio", category=Category.MESSAGING, name="Twilio",
        purpose="Send SMS and WhatsApp messages, and place calls.",
        unlocks="Reach a customer on the channel they actually answer.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_TWILIO_AUTH_TOKEN",
        setup_url="https://console.twilio.com",
        blocks=("outreach:sms", "outreach:whatsapp", "outreach:voice"),
        adapter_ready=False),
    Integration(
        id="resend", category=Category.MESSAGING, name="Resend",
        purpose="Deliver email with a reputation Qevik does not have to build from a bare host.",
        unlocks="Email that arrives, with delivery and bounce reporting.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_RESEND_API_KEY",
        setup_url="https://resend.com/api-keys",
        blocks=("outreach:email",),
        adapter_ready=False),
    Integration(
        id="slack", category=Category.WORKSPACE, name="Slack",
        purpose="Post into the channels a team already watches, and take instructions back.",
        unlocks="Approvals and reports where the team already is, instead of another inbox.",
        kind=ConnectionKind.OAUTH, credential="QEVIK_SLACK_BOT_TOKEN",
        setup_url="https://api.slack.com/apps",
        blocks=("notify:slack", "approval:slack"),
        adapter_ready=False),
    Integration(
        id="telegram", category=Category.MESSAGING, name="Telegram",
        purpose="A bot channel for alerts and quick approvals from a phone.",
        unlocks="Get told when something needs you, and answer without opening a laptop.",
        kind=ConnectionKind.API_TOKEN, credential="QEVIK_TELEGRAM_BOT_TOKEN",
        setup_url="https://core.telegram.org/bots#botfather",
        blocks=("notify:telegram",),
        adapter_ready=False),
    # --- social ------------------------------------------------------------
    Integration(
        id="meta", category=Category.SOCIAL, name="Meta (Facebook & Instagram)",
        purpose="Publish to Pages and Instagram accounts, and read how a post performed.",
        unlocks="Run a brand's Instagram and Facebook presence from the same queue as everything else.",
        kind=ConnectionKind.OAUTH, credential="QEVIK_META_ACCESS_TOKEN",
        setup_url="https://developers.facebook.com/apps",
        blocks=("social:facebook:publish", "social:instagram:publish", "social:meta:insights"),
        adapter_ready=False),
    Integration(
        id="tiktok", category=Category.SOCIAL, name="TikTok",
        purpose="Publish short video to a business account.",
        unlocks="The channel short-form video is actually watched on.",
        kind=ConnectionKind.OAUTH, credential="QEVIK_TIKTOK_ACCESS_TOKEN",
        setup_url="https://developers.tiktok.com",
        blocks=("social:tiktok:publish",),
        adapter_ready=False),
    Integration(
        id="linkedin", category=Category.SOCIAL, name="LinkedIn",
        purpose="Publish to a company page, where B2B buying attention is.",
        unlocks="Reach the people who sign contracts rather than the people who scroll.",
        kind=ConnectionKind.OAUTH, credential="QEVIK_LINKEDIN_ACCESS_TOKEN",
        setup_url="https://www.linkedin.com/developers/apps",
        blocks=("social:linkedin:publish",),
        adapter_ready=False),
    # --- workspace ---------------------------------------------------------
    Integration(
        id="google-workspace", category=Category.WORKSPACE, name="Google Workspace",
        purpose="Read and send from a business mailbox, and put things in its calendar and drive.",
        unlocks="Qevik works out of the same mailbox and calendar the business already runs on.",
        kind=ConnectionKind.OAUTH, credential="QEVIK_GOOGLE_WORKSPACE_REFRESH_TOKEN",
        setup_url="https://console.cloud.google.com/apis/credentials",
        blocks=("workspace:gmail", "workspace:calendar", "workspace:drive"),
        adapter_ready=False),
    Integration(
        id="notion", category=Category.WORKSPACE, name="Notion",
        purpose="Write research and briefs where a team already reads them.",
        unlocks="Deliverables land in the customer's own workspace, not in an export.",
        kind=ConnectionKind.OAUTH, credential="QEVIK_NOTION_TOKEN",
        setup_url="https://www.notion.so/my-integrations",
        blocks=("workspace:notion",),
        adapter_ready=False),
    # --- commerce ----------------------------------------------------------
    Integration(
        id="shopify", category=Category.COMMERCE, name="Shopify",
        purpose="Read a store's catalogue and orders, and write listings back.",
        unlocks="Product pages, descriptions and imagery generated against the real catalogue.",
        kind=ConnectionKind.OAUTH, credential="QEVIK_SHOPIFY_ACCESS_TOKEN",
        setup_url="https://admin.shopify.com",
        blocks=("commerce:shopify:catalogue", "commerce:shopify:orders"),
        adapter_ready=False),
)

BY_ID: dict[str, Integration] = {i.id: i for i in INTEGRATIONS}


def catalogue(store: ConnectionStore, *, tenant: TenantId | None) -> dict:
    """What is connected, what is waiting, and what is not built.

    Grouped rather than listed flat because the three groups are three different
    conversations: nothing to do, the customer's move, and ours.
    """
    described = [i.describe(store, tenant=tenant) for i in INTEGRATIONS]
    return {
        "connected": [d for d in described
                      if d["status"] == IntegrationStatus.CONNECTED.value],
        "pending_credential": [d for d in described
                               if d["status"] == IntegrationStatus.PENDING_CREDENTIAL.value],
        "not_implemented": [d for d in described
                            if d["status"] == IntegrationStatus.NOT_IMPLEMENTED.value],
        "note": "Nothing here holds a secret. A credential is stored as a "
                "reference under the connection that owns it, and its value is "
                "never shown again once supplied.",
    }


def blocked_capabilities(store: ConnectionStore, *, tenant: TenantId | None
                         ) -> frozenset[str]:
    """Everything that cannot run because a credential is missing."""
    blocked: set[str] = set()
    for integration in INTEGRATIONS:
        if integration.status(store, tenant=tenant) is not IntegrationStatus.CONNECTED:
            blocked.update(integration.blocks)
    return frozenset(blocked)
