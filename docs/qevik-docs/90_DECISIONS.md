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

D036 — An administrator with no customer tenant writes to `HOUSE_TENANT` and reads across all tenants, and those are two functions (`tenancy.of_user`, `tenancy.console_scope`) rather than one with a flag. The two answers genuinely differ for the same person, and hiding that behind a boolean is how one gets applied where the other belongs. `console_scope` also makes every cross-tenant read greppable: it either names `ALL_TENANTS` or calls that function.

D037 — `HOUSE_TENANT` is `tenant-qevik`, the name every worker unit already runs under. A second name for the house tenant would have written the operator's missions into a tenant no running worker watched: they would queue forever and nothing would say why. A test derives the constant from the unit files so the two cannot drift.

D038 — A `Timeline` owns exactly one factory and refuses to append another's events. Under the Postgres backend `_rows` filters by factory while `_append_row` wrote whatever the event carried, so a timeline used for credentials, chat, customer tasks or quota stored everything and read back nothing. The file backend has one file per timeline and no filter, so this failed only on a host with a database — every test and every laptop passed. Refusing an append that would succeed is deliberate: a store that accepts what it cannot return is data loss wearing a success.

D039 — `credentials.models.registry_for` passes the stored secret to the provider adapter. It previously built each adapter with a `key_env` and no key, so the vault decided only *whether* to register a provider while `os.environ` still supplied the secret — a credential could be stored, enabled and verified and fail every call, with the failure surfacing much later as a provider 401 that reads like a bad key.

D040 — A provider that authenticates and declines to bill raises `Unaffordable`, not `NotConfigured` or a generic `LLMError`. An empty Anthropic balance answers HTTP 400 and an unpurchased Aliyun model answers 403, so read by status alone the first looks like a malformed request and the second like a bad key — both send the reader to repair something that is not broken. The response body decides and never reaches the message.

D041 — A model's declared capabilities are established by calling it. `qwen-plus` was declared vision-capable, and answers image questions with HTTP 200 and "I can't view or analyze images" — the cheapest-capable policy made it the default choice for every vision request. Every model registered against a workspace is now one that was called against that workspace first: a Model Studio workspace serves what it has been granted and 403s the rest, so a catalogue copied from vendor documentation registers models the account cannot run.

D042 — `health()` distinguishes *absent* from *broken*. Its note always said "degraded means a component is absent, not that one failed", and there was no list to put a failure in, so a configured component reporting `healthy: False` appeared in neither and the summary read "ready" over an off-host backup that had failed every night. The dashboard's lead sentence changes with it: "Nothing needs you" printed over a broken backup is the screen reassuring the operator about the thing that is wrong.

D043 — The scheduler dispatches model work only against a *verified* credential (`usable_for` excludes `PENDING_CREDENTIAL`), and a worker re-reads the credential records before every dispatch check. It read them once at boot, so an operator testing a key in the Credential Centre moved it to CONNECTED and the worker went on refusing against its snapshot — two missions sat in `queued` reporting "needs qwen, anthropic, openai" while that centre said CONNECTED. Only a restart cleared it, which teaches an operator to restart things rather than to believe what a screen says.

D044 — The model-backed worker is given a real writable repository (`--origin notes=/srv/origins/notes`, created by `install_notes_origin.sh`). A worker with no origin can only accept missions declaring `none`, and `none` has no workspace: a coding agent then reports success, changes no file, and the worker refuses the claim three times and fails the mission. The refusal is right — an agent's "done" is a claim and the workspace decides — but it means a console conversation can never finish. `qevik` (self-modification) stays unavailable on a deployed host and needs no configuration to be absent: ADR-0010 ships a git archive, so there is no `.git` for the origin registry to offer.

D045 — Every page in the console's rail must appear in `CONSOLE_PATHS`, checked by deriving one list from the other. A page in one and not the other answers 401 on an HTML document when somebody bookmarks it, reloads it, or is sent the link — never on navigation, because the single-page app changes the hash and does not ask the server. Seven pages were in that state, found by comparing the lists rather than by following a link.

D046 — What an approval screen displays is what it sends. The origin picker showed a single available repository as a fact and rendered no input, so the approval posted an empty origin, which the API reads as Qevik's own source: the screen said "no source" and queued a self-modification mission.
