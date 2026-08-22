# Decision Log

D001 — Qevik is the current brand.

D002 — Do not broad-refactor Atlas internals yet. New environment variables use `QEVIK_`.

D003 — Google OAuth uses a Desktop client.

D004 — First Google capability is Gmail send.

D005 — Gmail channel does not duplicate OutreachService safety logic.

D006 — Connections have explicit ownership.

D007 — OpenClaw should run on a dedicated operator machine; P520 is preferred.

D008 — Z8 remains primarily a heavy AI/rendering machine.

D009 — Markdown project documentation is the portable project memory bridging ChatGPT, Claude, OpenClaw and Git.

D010 — Readiness scores eight dimensions, not the nineteen listed in `03_QEVIK_0_TO_100_AND_CASE_STUDIES.md`. The other eleven (video, social, ecommerce, marketplaces, advertising, CRM, email, analytics, automation, entity presence, image) have no research signal behind them, so scoring them would generate a number from nothing — which the same document forbids with "Unmeasured ≠ bad." They score `None` and surface as measurement tasks. Adding one means giving it real signals, not new machinery. The document stands; the implementation grows into it.

D011 — A confirmed weakness Qevik has no capability for is still shown, marked `NO_CAPABILITY`. Omitting it would make every plan capability-shaped — only the weaknesses Qevik sells against would appear, which reads to a customer as an audit and is not one.

D012 — Every customer-visible sentence in a roadmap passes the P1.4 attribution gate at `Attribution.UNKNOWN`. A plan is written before anything is measured, so nothing in it may license a causal claim. Enforced by the structured attribution model, not a string blacklist.

D013 — A roadmap task has no stored status. `TaskState` is folded from `RecommendationState`, `ApprovalState`, `JobStatus` and the roadmap's dependency graph. A stored status can disagree with the job it describes, and when it does nobody can tell which is lying.

D014 — `EXECUTORS` is the authority on what Qevik can execute, not the offer catalogue. An offer existing is not the same as something being able to perform it, and the roadmap presented five capabilities as executable that no executor exists for.

D015 — Approval fingerprints cover what the act *is* — capability, recommendation, evidence, title — and deliberately not the horizon. Invalidating a decision because a task was rescheduled would train people to re-approve without reading.

D016 — A baseline with no source raises rather than recording zero. A zero is a reading, and a reading nobody took makes every later comparison show improvement.

D017 — `portfolio_depth` is a defect signal, not a strength. `research/cms/base.py` emits it PRESENT meaning "N pages are photographs with almost no text", and `outreach/opportunity.py` uses that PRESENT as the trigger for the proof opportunity. Held in `readiness.INVERTED` rather than renamed, because three modules already agree on the name.

D018 — Publication requires a second approval, distinct from the execution approval. "Should Qevik do this work" and "may this exact output go to this exact destination" are different questions, asked at different times, and answerable differently by the same person. Different action names, so a policy can require a different approver for publication.

D019 — A `Connection` holds the *name* of a credential, never the credential. Construction refuses a reference that looks like a secret, because that value is written to events and reports. Resolution happens at the moment of use and re-checks tenant ownership, since a `Connection` is an ordinary value that can be passed anywhere.

D020 — A failed publication is a record, not an exception. Losing it would leave a customer's site in an unknown state with nothing written down. A retry is a new record; the failed one stays.

D021 — The bytes published must hash to the approved asset's content hash. The approval fingerprint covers the hash and the files are a separate argument — without this check an approval for one artefact could publish another.

D022 — A capability's output is a *bundle* — a mapping of path to text — and a single document is a bundle with one entry. `execution/artefacts.bundle_hash` is the only identity function for one. Two hashing rules would drift, and the publication gate compares published bytes against the approved hash, so the drift would either refuse everything or refuse nothing.

D023 — The website capability's mode (CREATE / MODIFY) is derived from whether research could read a site, and `build_website` has no mode parameter. Letting a caller declare "create" is how a business with a working website gets a new one built over the top of it.

D024 — `build_website` raises when a site already does everything the capability could add. A strong website is a finding, not a reason to rebuild it, and the refusal means no artefact exists to approve, publish or bill for.

D025 — Every `CapabilityOffer` must have an `OFFER_DIMENSION` entry, checked at import. Without it a new offer produces roadmap tasks with no dimension and no metric — they schedule, are approved, execute, and nothing can ever be measured about them.

D026 — A website has four states, not two: ABSENT, UNVERIFIED, WEAK, STRONG. DNS separates the first two — a name server answering "no such host" is conclusive, a timeout establishes nothing. UNVERIFIED produces no opportunity and no build; missing research stays UNKNOWN rather than becoming a weakness.

D027 — DNS is asked only after the HTTP request has failed. Asking first spends a lookup on every healthy site and overrides a caller's injected HTTP transport with the real network.

D028 — STAGED is a distinct state from PUBLISHED and is checkable, not assumed: `is_live()` asks the target which version visitors get. Staging before QA passes is refused, because a fetchable link to a rejected page inside an approval request is one somebody will approve.

D029 — A publication record's `completed_at` is the measurement's `intervention_at`. A failed publication is never an intervention: nothing went live, so a window opened against it would measure work that never happened.

D030 — Re-evaluation classifies each change (improved / worsened / resolved / no longer required) from the scores rather than from whether a task disappeared. Work leaves a plan for three different reasons and only one of them is good news.

D031 — A user carries the tenant they act for, and an empty value means *not established* rather than *any*. `current_tenant` refuses instead of falling back: an implicit default would make every downstream ownership check pass for whichever tenant it named, and each one would look correct in review.

D032 — Another tenant's resource is absent, not forbidden. Identical 404 and identical body for "does not exist" and "not yours", because the difference tells an attacker which ids exist and enumerating ids is the cheapest attack there is.

D033 — A customer task is complete only with proof, and the proof kind is recorded. An attestation is legitimate where a thing genuinely cannot be checked, and it must name who attested — an unsigned one is an unsourced claim in the customer's file.

D034 — The public boundary is an allow-list, not a redaction. A deny-list silently passes whatever field was added last, and the cost of being wrong is a stranger's private data on a marketing page. The public audit counts findings rather than naming them.

D035 — `measurement/schedule.py` answers "what is due" and is not a scheduler. Building a worker before anything needs one produces a background process that runs forever doing nothing; the query is the part that would still be needed afterwards.
