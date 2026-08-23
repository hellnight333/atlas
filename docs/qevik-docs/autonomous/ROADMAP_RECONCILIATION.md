# Roadmap reconciliation

**Written 2026-08-23.** Reconciles three document sets that number their phases
differently and describe partly different products. Neither original is
modified; this is the map between them.

---

## The finding that matters

There are **two different products** in the documentation, and they are not
alternative descriptions of one thing.

**Product A — the evidence engine.** `01_QEVIK_PHASE_ROADMAP.md`, P1–P8.
Research a business, derive evidence, find opportunities, recommend, plan,
approve, execute, QA, stage, approve again, publish, measure, re-evaluate. This
is what the repository implements, and it is substantially built.

**Product B — the execution platform.** `QEVIK_PENDING_IMPLEMENTATION_DOCS/`
docs 01–10, Phase 1–12. A controlled environment in which a coding agent, a
browser worker and an Iran-origin worker perform real computer work on request,
so a human stops copy-pasting between ChatGPT, Claude, VS Code and a terminal.
This is **almost entirely unbuilt**.

**Product C — a media/growth business.** Docs 11 and 11A. YouTube kids-music
channels, a game factory, an app factory, with its own gap analysis. This is a
*different business line*, not a layer of Qevik.

They overlap at four points only: publishing, the control plane, the public
website, and commercialization. Everywhere else they are separate programmes.

`00_QEVIK_IMPLEMENTATION_DOCS_INDEX.md` settles precedence itself: these
documents *supplement* rather than replace, and where two conflict "the
repository's current authoritative project-state/decision documents take
precedence until the conflict is explicitly resolved."

**So: `01_QEVIK_PHASE_ROADMAP.md` remains authoritative. The pending docs are a
second programme that has not been started, not a correction to the first.**

---

## Document-by-document

| Doc | Specifies | Phase | Status | Note |
|---|---|---|---|---|
| 00 index | Reading order, precedence | — | N/A | Settles precedence: repo state wins |
| 01 master execution plan | Phase 1–12: infra, execution engine, agent adapter, browser, publishing, Iran worker, workers, control UI, product site, factories, commercial | Parallel | **NOT_STARTED** except where P1–P8 already covers it | Different numbering; see mapping |
| 02 browser + agent | Coding-agent and browser execution adapters | 01/Phase 4–5 | **NOT_STARTED** | Needs a sandbox host; `browser/` exists as an interface only |
| 03 Iran worker | Genuine Iran-origin checks | 01/Phase 7 | **PENDING_EXTERNAL** | Requires an Iran-resident host. Cannot be faked — the doc says so explicitly |
| 04 website factory | request → deploy → verify | 01/Phase 11 | **PARTIAL** | P2/P2.1–P2.3 built generation, QA, staging, artefact approval, publication to a local target. Deploy-to-real-host and browser verification missing |
| 05 app/game/content factories | App, game, content pipelines | 01/Phase 11 | **NOT_STARTED** | Content partly covered by the editorial capability |
| 06 control plane + mobile | Phone/browser control surface | 01/Phase 9 | **PARTIAL** | Action centre and read APIs exist; no UI, no live logs, no retry/cancel |
| 07 security/secrets/approvals | Secret handling, approvals, audit | Cross-cutting | **SUBSTANTIALLY_COMPLETE** | `Connection` references, `ApprovalService`, two approval boundaries, tenant isolation, `db_safety`. Gaps: rate limiting, webhook verification, SSRF |
| 08 deployment/observability/backup | Supervision, health, backup/restore | 01/Phase 2 | **NOT_STARTED** in this repo | Operational, not application code |
| 09 public website + commercial | qevik.ai site and commercial layer | 01/Phase 10 + P4 | **PARTIAL** | Public audit route and plan surface exist; no website, no signup, no billing |
| 10 acceptance tests | Executable checklist A–F | — | **MOSTLY_UNMET** | See below |
| 11 media/growth engine | YouTube/game/app business | Separate line | **NOT_STARTED** | Different business; not a Qevik layer |
| 11A gap analysis | Tier 1–3 gaps for doc 11 | Separate line | **NOT_ACTIONABLE_BY_AGENT** | Legal entity, developer accounts, API quotas, IP rights, brand clearance — business decisions, not code |

## Acceptance checklist (doc 10) against the repository

| Group | Status |
|---|---|
| A. Core — db init, restore, API health, suite, lint/types | **PARTIAL** — suite/lint/types green; no restore procedure, no supervised service |
| B. Coding execution — agent edits, tests, commits | **NOT_STARTED** |
| C. Browser — open, extract, screenshot, forms, crawl | **PARTIAL** — research crawls; no browser worker, no screenshots |
| D. Deployment — build, deploy, HTTPS, public URL, verify | **PARTIAL** — local target proven; no public URL, no HTTPS verification |
| E. Iran — Iran-origin checks | **PENDING_EXTERNAL** |
| F. Persistence — survive disconnect, resume | **NOT_STARTED** |

## Phase mapping

| Pending doc phase | Nearest P1–P8 | Reality |
|---|---|---|
| Phase 2 core infra | — | Operational; outside the kernel |
| Phase 3 execution engine | P1.3/P1.6 | Job/Run/approval/provenance exist; retries, cancellation, resumability do not |
| Phase 4 agent execution | — | Not started; the largest single unbuilt piece |
| Phase 5 browser | — | Not started |
| Phase 6 publishing | P2.1 | Architecture complete; only a local target connected |
| Phase 7 Iran worker | — | Externally blocked |
| Phase 9 control interface | §3/§4 of the master directive | Action centre + read APIs; no UI |
| Phase 10 product website | P4 | Audit route + plan surface only |
| Phase 11 factories | P2 | Website factory partial; others not started |
| Phase 12 commercialization | P1.7/P4 | Plans, credits, quota done; billing deliberately absent |

## What this changes about execution order

Three things follow, and they are the reason this document exists rather than a
longer task list.

**The pending docs do not renumber P1–P8.** They are a second programme. Work
should continue to be numbered against `01_QEVIK_PHASE_ROADMAP.md`, and
Product B items referred to by their doc number.

**Product B is gated on infrastructure this agent cannot provision.** A coding-
agent sandbox, a browser worker and an Iran-resident host are hosts, not
modules. The application-side contracts can be built; the workers cannot.

**Docs 11/11A are a different business.** Implementing them inside this
repository would put a YouTube media operation inside a B2B evidence engine.
That is a commercial decision, and its own gap analysis lists legal entity,
developer accounts and IP rights as Tier 1 — none of which is code.
