# QEVIK — AUTONOMOUS MEDIA, GAME & DIGITAL BUSINESS ENGINE

## Status

This document is an implementation specification, not an estimation document.

Claude Code must implement the required system in the existing Qevik repository and infrastructure. Do not merely create tickets, mock interfaces, or describe future work. Implement the smallest production-capable vertical slices, test them, and continue until the acceptance criteria are met.

This document supplements the existing Qevik architecture, master execution plan, browser-agent architecture, Iran worker specification, website/app/game/content factory specifications, security/approval documents, deployment documents, and acceptance tests.

It adds the missing **business-operation layer** above the factories:

> research → create → quality-control → publish → measure → learn → iterate → monetize → manage inbound business

---

# 1. BUSINESS OBJECTIVE

Qevik must be able to operate digital-product and media businesses from high-level instructions without requiring the user to manually copy/paste between ChatGPT/Claude, editors, browser tabs, dashboards, publishing platforms, and analytics.

Example user request:

> "Create a kids channel around a funny rabbit wearing a hat. Make a song, animation, thumbnail and metadata, publish it, monitor performance, and keep producing the next episodes."

Qevik should turn this into durable jobs.

Another example:

> "Make 12 small games today, test them, prepare store listings, publish the ones that pass, and report downloads, revenue and failures."

Another:

> "Find businesses without websites, build websites for qualified prospects, publish them to preview URLs, track outreach, and put replies into the Qevik Inbox."

Another:

> "A company emailed asking about sponsorship. Summarize the conversation, estimate whether it is commercially relevant, draft a response and ask me before sending."

The user should not need to manually move artifacts between systems.

---

# 2. IMPORTANT ARCHITECTURAL BOUNDARY

Do NOT create one giant "social media agent".

Use the existing Qevik capability / worker / task / artifact architecture.

Add business-domain services:

- Brand
- Channel
- Content Series
- Content Item
- Game Portfolio
- App Portfolio
- Publishing Account
- Publishing Job
- Analytics Snapshot
- Experiment
- Revenue Event
- Sponsorship Lead
- Conversation
- Contact
- Campaign
- Opportunity
- Approval
- Commercial Offer

All become durable records linked to Qevik tasks and artifacts.

---

# 3. PORTFOLIO MODEL

Qevik must support multiple independent businesses/projects simultaneously.

Example:

```text
Portfolio
├── Kids Rabbit Channel
│   ├── YouTube
│   ├── Instagram
│   ├── TikTok
│   └── Website
│
├── Game Portfolio
│   ├── Game 001
│   ├── Game 002
│   ├── Game 003
│   └── ...
│
├── Website Business
│   ├── Prospect A
│   ├── Prospect B
│   └── ...
│
└── Qevik
    ├── Public Website
    ├── Product
    └── Commercial Inbox
```

Every portfolio item must have:

- owner
- brand
- status
- platforms
- credentials references
- content rules
- target audience
- monetization strategy
- analytics
- artifacts
- publishing history
- revenue
- costs
- tasks
- approvals
- audit trail

---

# 4. BRAND / CHANNEL ENGINE

Implement a reusable Brand and Channel system.

Each Brand contains:

- name
- visual identity
- voice
- audience
- geography
- language
- content categories
- prohibited topics
- characters
- recurring formats
- publishing schedule
- monetization goals
- platform accounts
- website
- contact email

Each Channel contains:

- platform
- account reference
- channel/page URL
- publishing permissions
- audience classification
- analytics connector
- monetization status
- content policy status
- credentials reference
- last sync
- health status

Do not store raw credentials in application tables.

---

# 5. CONTENT SERIES ENGINE

A series is a repeatable production format.

Example:

```text
Series:
Rabbit Hat Adventures

Character:
Funny rabbit wearing a hat

Formats:
- 20–40 second Shorts
- 2–3 minute songs
- 5 minute stories
- thumbnails
- Instagram Reels
- promotional images
```

Series should define:

- canonical characters
- style bible
- music style
- voice
- recurring locations
- episode templates
- title patterns
- thumbnail patterns
- metadata templates
- safety rules
- target audience
- publishing platforms

Qevik must maintain character/style consistency across episodes.

---

# 6. CONTENT PRODUCTION LOOP

For every content request:

```text
Brief
 ↓
Research
 ↓
Concepts
 ↓
Selection
 ↓
Script
 ↓
Storyboard
 ↓
Assets
 ↓
Voice/music
 ↓
Animation/video
 ↓
Edit
 ↓
Subtitles
 ↓
Thumbnail
 ↓
Metadata
 ↓
Policy checks
 ↓
Quality checks
 ↓
Platform-specific packaging
 ↓
Publish
 ↓
Verify
 ↓
Analytics
 ↓
Learning record
```

The system must preserve every intermediate artifact.

---

# 7. KIDS CONTENT MODE

Implement an explicit `kids_content` classification.

Do not infer this only from title or visual appearance.

For content that is directed to children:

- require explicit audience classification
- apply platform-specific child-safety rules
- validate metadata
- validate sponsorship rules
- avoid prohibited or inappropriate content
- record why the audience classification was chosen
- require human approval for ambiguous cases

YouTube's current policies restrict personalized advertising on content set as made for kids. This can affect monetization, so the analytics model must distinguish:

- views
- monetized playbacks where available
- RPM/CPM where available
- estimated revenue
- non-ad revenue
- sponsorship revenue

Do not promise revenue based only on view count.

---

# 8. YOUTUBE OPERATIONS

Implement a YouTube connector abstraction.

Required capabilities:

- create/upload video
- upload thumbnail
- set title
- description
- tags where supported
- playlist management
- audience setting
- scheduling
- visibility
- subtitles/captions
- retrieve video status
- retrieve analytics
- retrieve comments where API permissions allow
- detect publishing failures
- record video URL
- record YouTube video ID
- sync channel metrics
- detect monetization status
- maintain channel health

Publishing must be idempotent.

Never upload the same content twice because a network request timed out.

---

# 9. YOUTUBE MONETIZATION TRACKING

Create a MonetizationEligibility record.

Track at minimum:

- subscribers
- public uploads
- public watch hours
- Shorts views
- YPP application state
- AdSense connection state
- monetization feature state
- review state
- policy warnings/strikes where accessible
- estimated revenue
- finalized revenue when available

As of the current YouTube documentation, expanded YPP access can begin at 500 subscribers plus 3 public uploads in 90 days and either 3,000 public watch hours in 12 months or 3 million valid Shorts views in 90 days, while ad/Premium revenue sharing requires 1,000 subscribers plus either 4,000 valid public watch hours in 12 months or 10 million valid Shorts views in 90 days.

These thresholds must NOT be hard-coded permanently. Put them in a policy/configuration layer and periodically re-check official platform documentation.

---

# 10. INSTAGRAM / SOCIAL PUBLISHING

Implement a generic SocialPublisher interface.

Capabilities should include where officially supported:

- account connection
- media upload
- Reel/video publishing
- image publishing
- captions
- hashtags
- scheduling
- status retrieval
- permalink retrieval
- analytics
- comments/messages where API permissions allow

Do not design around scraping a platform if an official API is available.

Browser automation is the fallback for workflows that are permitted but not available through APIs.

The system must clearly label:

- API action
- browser action
- human action required

---

# 11. MULTI-PLATFORM CONTENT ADAPTATION

One master content item may produce:

```text
Master video
├── YouTube long-form
├── YouTube Short
├── Instagram Reel
├── TikTok version
├── thumbnail
├── teaser
├── still image
└── website embed
```

Do not simply duplicate the same file.

Generate platform-specific:

- aspect ratio
- duration
- captions
- title
- description
- CTA
- thumbnail
- metadata

Maintain lineage:

```text
Master Artifact
    ↓
Derived Artifact
    ↓
Platform Publication
```

---

# 12. CONTENT CALENDAR

Implement a calendar for each brand.

Calendar fields:

- planned publish time
- platform
- content item
- series
- status
- priority
- target
- actual publish time
- performance

Support:

- daily
- weekly
- campaign
- batch publishing
- evergreen
- experimental

Qevik should be able to generate a calendar automatically.

---

# 13. HIGH-VOLUME GAME FACTORY

The objective is to make **many small games**, not to pretend that 10–12 polished commercial games every day is automatically realistic.

Implement a throughput-oriented pipeline for small games:

```text
Idea
 ↓
Market/relevance research
 ↓
Novelty check
 ↓
Game design
 ↓
Prototype
 ↓
Automated play/test
 ↓
Visual/audio generation
 ↓
Build
 ↓
Store package
 ↓
Store listing
 ↓
Policy checks
 ↓
Human approval where required
 ↓
Publish
 ↓
Analytics
 ↓
Kill / iterate / update
```

The scheduler must support daily batch targets such as:

```text
target_games_per_day = 12
```

But quality gates determine how many actually ship.

Example:

```text
12 concepts
→ 12 prototypes
→ 9 pass basic QA
→ 6 pass originality/policy checks
→ 4 worth publishing
```

This is preferable to publishing 12 low-quality games.

---

# 14. GAME PORTFOLIO ANALYTICS

For every game track:

- impressions
- store page views
- installs
- conversion rate
- active users
- retention
- session length
- crashes
- ratings
- reviews
- ad revenue
- IAP revenue
- subscription revenue
- refunds
- acquisition source
- development cost
- infrastructure cost
- estimated profit

Create automatic classifications:

- SCALE
- ITERATE
- HOLD
- KILL

Do not kill a game using one day's data if the sample size is insufficient.

---

# 15. GOOGLE PLAY PUBLISHING

Implement a Google Play publishing adapter.

Track:

- developer account
- application IDs
- package name
- signing
- release tracks
- internal testing
- closed testing
- production
- store listing
- screenshots
- feature graphic
- privacy policy URL
- data safety information
- content rating
- target audience
- review status
- release status
- installs
- ratings
- revenue

Important current constraint:

New personal Play Console accounts created after November 13, 2023 have a closed-testing requirement of at least 12 opted-in testers for 14 continuous days before production access can be requested.

Therefore Qevik must NOT assume:

```text
build → upload → instantly public
```

The publishing state machine must understand:

```text
DRAFT
INTERNAL_TEST
CLOSED_TEST
PRODUCTION_ACCESS_PENDING
PRODUCTION
REJECTED
SUSPENDED
```

---

# 16. APPLE PUBLISHING

Implement an App Store Connect adapter abstraction.

Support the lifecycle where the connected account/API permissions allow:

- app creation
- metadata
- screenshots
- builds
- TestFlight
- release submission
- review state
- release
- analytics
- crash information
- revenue

Never claim an app was published until the platform confirms the release.

---

# 17. WEBSITE BUSINESS FACTORY

The existing Website Factory must be extended into a commercial prospecting workflow.

Example:

```text
Research businesses
 ↓
Find businesses with poor/no website
 ↓
Score opportunity
 ↓
Create prospect record
 ↓
Research business
 ↓
Generate website concept
 ↓
Build website
 ↓
Deploy preview
 ↓
Verify
 ↓
Generate outreach
 ↓
Send only when authorized
 ↓
Track response
 ↓
Inbox
 ↓
Opportunity
 ↓
Proposal
 ↓
Customer
```

Do not mass-spam.

Use qualification and rate limits.

---

# 18. BUSINESS RESEARCH ENGINE

Allow requests such as:

> "Find 100 businesses in Dubai with no modern website."

The system should:

- research candidates
- collect public business information
- detect website existence
- assess website quality
- score opportunity
- avoid duplicates
- store source evidence
- generate prospect records
- optionally create previews

For every prospect store:

- company
- website
- country
- city
- public contact channels
- evidence
- research date
- score
- reason
- status

Respect robots.txt, platform terms, privacy rules, rate limits, and applicable law.

---

# 19. INBOX — CRITICAL

Build a unified Qevik Inbox.

The Inbox is not simply email.

It should unify:

```text
Email
YouTube comments
Instagram messages/comments where API permissions allow
Website contact forms
Business inquiries
Sponsorship requests
App-store feedback where accessible
Customer support
Internal Qevik notifications
```

Each conversation:

```text
Conversation
├── participants
├── channel
├── messages
├── attachments
├── company/contact
├── related project
├── related content
├── related game
├── sentiment
├── intent
├── priority
├── status
├── assigned agent
├── suggested reply
├── approval state
└── audit trail
```

---

# 20. INBOX FEATURES

The user should see:

- All
- Unread
- Important
- Sponsorship
- Customers
- Prospects
- YouTube
- Instagram
- Business
- Support
- Spam
- Waiting for me

Each conversation should show:

- summary
- latest message
- suggested response
- conversation history
- related artifacts
- related revenue
- contact/company
- next action

Qevik should automatically summarize long conversations.

---

# 21. RESPONSE AGENT

The agent may:

- classify message
- summarize
- extract requirements
- detect commercial opportunity
- draft reply
- propose next action
- create task
- create CRM opportunity
- schedule follow-up

Sending rules:

### Low-risk
Examples:
- routine support response
- approved template
- known recipient
- no financial/legal commitment

May be auto-sent if the user explicitly enables that policy.

### High-risk
Require human approval:

- sponsorship price
- contract
- refund
- payment
- legal statement
- public accusation
- account changes
- deletion
- sensitive personal information
- unusual external commitment

---

# 22. SPONSORSHIP CRM

Implement sponsorship opportunities as first-class objects.

Fields:

- company
- contact
- email
- website
- platform
- campaign
- content proposal
- expected audience
- offer
- currency
- requested deliverables
- deadline
- status
- negotiation history
- contract artifact
- invoice
- payment
- actual revenue

Pipeline:

```text
NEW
 ↓
QUALIFIED
 ↓
CONTACTED
 ↓
REPLIED
 ↓
NEGOTIATING
 ↓
OFFER_RECEIVED
 ↓
APPROVAL
 ↓
CONTRACTED
 ↓
CONTENT_PRODUCTION
 ↓
PUBLISHED
 ↓
INVOICED
 ↓
PAID
```

---

# 23. SPONSORSHIP DETECTION

The Inbox agent should detect phrases indicating commercial interest, for example:

- sponsorship
- partnership
- collaboration
- brand deal
- paid promotion
- campaign
- advertising
- affiliate
- ambassador
- product placement

It should create a Sponsorship Lead automatically.

It must not accept an offer or quote a binding price without the configured approval policy.

---

# 24. SPONSORSHIP DISCLOSURE

For YouTube paid promotions, Qevik must support the platform's paid-promotion disclosure workflow.

Paid promotions must be handled according to YouTube policy and applicable law.

For children's content, sponsorship rules require additional care. Do not automatically insert commercial material into children's content simply because a sponsor requests it.

Store:

- sponsor
- disclosure requirement
- disclosure text
- platform
- jurisdiction
- approval
- publication evidence

---

# 25. REVENUE ENGINE

Create a unified revenue ledger.

Revenue sources:

- YouTube advertising
- YouTube Premium
- sponsorships
- affiliate revenue
- game advertising
- game IAP
- subscriptions
- app sales
- website customers
- services
- licensing
- other

For each revenue event:

- source
- platform
- project
- artifact
- currency
- gross
- platform fee
- tax where known
- net
- date
- confidence
- finalized/estimated

Never mix estimated and finalized revenue without labeling.

---

# 26. COST ENGINE

Track:

- GPU electricity cost where measurable
- cloud GPU
- API/model usage
- storage
- bandwidth
- domains
- hosting
- platform fees
- advertising spend
- contractor costs
- software subscriptions

Then calculate:

```text
Revenue
- platform fees
- infrastructure
- generation/API
- advertising
- other direct costs
= contribution margin
```

---

# 27. EXPERIMENT ENGINE

Qevik should not simply publish content.

It should learn.

Experiments:

- thumbnail A/B
- title variations
- hook variations
- video duration
- posting time
- character
- music style
- game mechanic
- store icon
- store description

Each experiment must have:

- hypothesis
- variable
- control
- variant
- sample size
- result
- confidence
- decision

---

# 28. AUTOMATED DAILY BUSINESS LOOP

Implement a scheduler that can execute:

```text
06:00
Research trends/opportunities
 ↓
Generate daily production plan
 ↓
Create games
 ↓
Create videos
 ↓
Create social assets
 ↓
Run QA
 ↓
Publish approved items
 ↓
Sync analytics
 ↓
Evaluate yesterday's content
 ↓
Update strategy
 ↓
Check Inbox
 ↓
Classify commercial leads
 ↓
Draft responses
 ↓
Request approvals
 ↓
Generate daily business report
```

The exact time must be configurable.

---

# 29. DAILY PRODUCTION DASHBOARD

Create a dashboard showing:

### Today

- games created
- games published
- videos created
- videos published
- posts published
- websites created
- prospects researched
- emails received
- important conversations
- sponsorship leads
- revenue
- cost
- profit

### Portfolio

- total games
- total downloads
- total active users
- total video views
- subscribers
- followers
- estimated revenue
- realized revenue
- sponsorship pipeline

### Problems

- failed builds
- rejected uploads
- policy warnings
- API failures
- account authentication failures
- content QA failures

---

# 30. AUTOMATIC REPORTING

Generate:

### Daily report
- production
- publishing
- performance
- revenue
- costs
- important inbox
- sponsorships
- failures
- recommended actions

### Weekly report
- best content
- worst content
- best games
- worst games
- revenue trend
- cost trend
- channel growth
- experiments
- opportunities
- next week's production plan

### Monthly report
- P&L-style summary
- platform breakdown
- portfolio breakdown
- monetization progress
- sponsorship revenue
- customer revenue
- strategic recommendations

---

# 31. ACCOUNT / CREDENTIAL ARCHITECTURE

Accounts must be represented as connections, not plain-text credentials.

Examples:

- Google
- YouTube
- Instagram/Meta
- TikTok
- Google Play
- Apple
- GitHub
- domains/DNS
- email
- payment providers

Use secret references.

Never place:

- API keys
- OAuth refresh tokens
- passwords
- private keys

in Git.

---

# 32. BROWSER AUTOMATION

If an official API does not expose an operation and browser automation is permitted, Qevik may use the Browser Worker.

Every browser workflow must record:

- account
- browser profile
- task
- URL
- actions
- screenshots/evidence
- result
- errors

Persistent authenticated browser profiles must be encrypted/protected.

Do not bypass CAPTCHA, MFA, platform anti-abuse mechanisms, or access controls.

When MFA/CAPTCHA requires a human, pause the task and request intervention through the Qevik control surface.

---

# 33. IRAN VERIFICATION

For websites/businesses where Iranian accessibility matters:

```text
Publish
 ↓
European/Hetzner verification
 ↓
Iran Worker verification
 ↓
Compare
 ↓
Report:
  GLOBAL: PASS
  IRAN: PASS/FAIL
```

Do not claim Iranian accessibility based on a foreign server.

For every check record:

- timestamp
- origin
- DNS result
- HTTP result
- browser result
- screenshot
- failure reason

---

# 34. QUALITY GATES

No content should be published merely because generation succeeded.

Required checks may include:

### Video
- file integrity
- duration
- resolution
- audio
- subtitles
- black-frame detection
- visual corruption
- policy classification
- duplicate detection

### Game
- launch
- crash
- basic gameplay
- input
- FPS where relevant
- store asset completeness
- privacy/data disclosures
- package signing
- platform policy checks

### Website
- build
- routes
- mobile
- links
- forms
- console
- API
- deployment
- Iran verification where requested

---

# 35. ORIGINALITY / DUPLICATION CONTROL

High-volume production must not become automated duplicate spam.

For every asset/content item compute:

- perceptual hash where appropriate
- semantic similarity
- source lineage
- reused assets
- reused script structure
- reused metadata

Flag:

- near-duplicate videos
- near-identical games
- copied store descriptions
- repeated thumbnails
- repetitive children's content

Require a quality decision before publishing suspicious batches.

---

# 36. POLICY ENGINE

Create platform-policy adapters.

Policies must be versioned and periodically refreshed from official sources.

Do not hard-code assumptions permanently.

Policy checks should cover:

- audience classification
- copyright
- music
- images
- trademarks
- paid promotion
- children
- privacy
- app store requirements
- prohibited content
- spam/low-quality behavior
- platform-specific metadata

The policy engine should return:

```text
PASS
WARN
BLOCK
HUMAN_REVIEW
```

---

# 37. USER APPROVAL CENTER

The user should not have to open five different platforms.

Qevik should show:

```text
APPROVALS

[Approve] [Reject] [Edit]

YouTube sponsorship reply
Google Play production release
New Instagram account connection
$1,500 sponsorship offer
New domain purchase
Payment/refund
```

The user can approve from:

- desktop browser
- mobile browser
- future mobile app

---

# 38. MOBILE-FIRST OPERATIONS

The user should be able to say from a phone:

> "Make 5 more rabbit videos."

or:

> "Publish the 3 games that passed QA."

or:

> "Show me important emails."

or:

> "Reply to this sponsor: ask them for their budget and deliverables."

Qevik creates a task.

The task continues on the server/workers after the phone disconnects.

---

# 39. NO MANUAL COPY/PASTE PRINCIPLE

Normal workflow must be:

```text
User
 ↓
Qevik
 ↓
Planner
 ↓
Workers / APIs / Browser
 ↓
Artifact
 ↓
Publish
 ↓
Analytics
 ↓
Inbox / Report
```

NOT:

```text
User
 ↓
copy prompt
 ↓
Claude
 ↓
copy result
 ↓
VS Code
 ↓
copy file
 ↓
browser
 ↓
copy URL
 ↓
dashboard
```

Manual intervention should be reserved for:

- credentials
- MFA/CAPTCHA
- legal/financial approvals
- ambiguous policy
- high-value commercial decisions
- exceptional failures

---

# 40. FIRST PRODUCTION VERTICAL

Do not attempt every platform simultaneously.

Build one complete vertical slice first:

## Rabbit Kids Channel

Input:

> "Create a funny rabbit wearing a hat, dancing to an original children's song."

Qevik must:

1. create the brand
2. create canonical rabbit character
3. create style bible
4. create song concept
5. create lyrics/music
6. create storyboard
7. generate assets
8. generate animation/video
9. create thumbnail
10. create title/description
11. classify audience
12. run policy checks
13. render final video
14. upload to YouTube through the supported connector
15. verify publication
16. store URL
17. record analytics baseline
18. create derivative social asset
19. schedule/publish where authorized
20. return a complete execution report

No manual copy/paste should be necessary after accounts are connected.

---

# 41. SECOND PRODUCTION VERTICAL

## Game Batch

Input:

> "Make 12 small games today."

Qevik must:

1. research/derive concepts
2. score concepts
3. generate 12 specifications
4. build prototypes
5. test them
6. reject failures
7. generate assets
8. build packages
9. prepare store listings
10. run policy/completeness checks
11. publish only eligible games
12. record store IDs
13. monitor downloads
14. monitor crashes/reviews
15. calculate economics
16. recommend SCALE / ITERATE / HOLD / KILL

The system must make the throughput configurable.

---

# 42. THIRD PRODUCTION VERTICAL

## Sponsorship Inbox

Input:

> "Check my inbox and handle business opportunities."

Qevik must:

1. sync connected inboxes
2. classify messages
3. identify sponsorships
4. summarize
5. create CRM opportunity
6. estimate commercial relevance
7. draft response
8. ask approval where required
9. send when authorized
10. track reply
11. schedule follow-up
12. attach contract/payment artifacts
13. track realized revenue

---

# 43. ACCEPTANCE TESTS

The implementation is NOT complete until these can be demonstrated.

### Test A — Content
User asks for a rabbit video.

Expected:
- task created
- assets generated
- final video produced
- QA passed
- metadata created
- publication attempted
- publication verified
- artifact lineage stored

### Test B — Game batch
User requests 12 games.

Expected:
- 12 jobs created
- independent build/test results
- failed games isolated
- eligible games packaged
- publication workflow started
- analytics records created

### Test C — Inbox
A test sponsorship email arrives.

Expected:
- imported
- classified
- summarized
- sponsorship lead created
- draft reply generated
- approval requested if policy requires

### Test D — Analytics
A published item receives metrics.

Expected:
- metrics synced
- revenue state updated
- dashboard updated
- experiment/portfolio metrics updated

### Test E — Mobile
User submits a task from a mobile browser.

Expected:
- task persists
- user can close browser
- worker continues
- user can reopen later
- complete result is available

### Test F — Iran
A website is deployed.

Expected:
- global verification
- Iran-origin verification
- separate results
- screenshots/evidence

---

# 44. IMPLEMENTATION ORDER

Claude Code should implement in this order:

## Priority 1
- durable business entities
- publishing abstraction
- account/connection abstraction
- Inbox
- content/channel model
- analytics model

## Priority 2
- YouTube vertical slice
- Rabbit kids content vertical
- publication verification
- analytics sync

## Priority 3
- social publishing abstraction
- content calendar
- derivative content

## Priority 4
- game batch pipeline
- Google Play publishing state machine
- Apple publishing adapter

## Priority 5
- sponsorship CRM
- response agent
- revenue/cost ledger

## Priority 6
- experimentation
- portfolio optimization
- automatic daily/weekly planning

## Priority 7
- scale workers
- increase production throughput
- improve autonomous operation

Do not postpone the Inbox or business/revenue layer until after the media factory. They are part of the product objective.

---

# 45. NON-NEGOTIABLE PRINCIPLES

1. Qevik must operate through durable tasks.
2. Every generated item has provenance.
3. Every external publication has verification.
4. Every revenue number has a source and confidence state.
5. Every account connection is permissioned.
6. High-risk side effects require approval unless explicitly configured otherwise.
7. Platform rules must be treated as changing external policy.
8. Never claim a publication succeeded without platform evidence.
9. Never claim monetization eligibility without current platform evidence.
10. Never use foreign infrastructure to fake Iranian accessibility.
11. Do not build a spam machine.
12. Optimize for quality-adjusted throughput, not raw artifact count.
13. The user should not need to copy/paste between systems.
14. The phone is a control surface, not the execution environment.
15. Qevik Core owns orchestration and state; workers perform specialized work.

---

# 46. DEFINITION OF DONE

This layer is complete when the user can realistically say:

> "Make a rabbit kids channel."

and Qevik can execute the connected workflow.

And:

> "Make 12 games."

and Qevik can batch-build, test, package, publish eligible games, and track results.

And:

> "Check my inbox."

and Qevik can show important conversations and commercial opportunities.

And:

> "What made money this week?"

and Qevik can produce a sourced portfolio-level answer.

And:

> "A sponsor contacted us."

and Qevik can identify it, summarize it, create an opportunity, draft the response, and route the final decision through the appropriate approval policy.

The final user experience should be:

```text
USER
  ↓
QEVIK
  ↓
PLAN
  ↓
RESEARCH
  ↓
CREATE
  ↓
TEST
  ↓
PUBLISH
  ↓
VERIFY
  ↓
MEASURE
  ↓
LEARN
  ↓
MONETIZE
  ↓
INBOX
  ↓
NEXT ACTION
```

This is the missing operational business layer on top of the existing Qevik execution architecture.
