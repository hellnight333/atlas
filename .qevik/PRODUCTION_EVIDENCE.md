# QEVIK PRODUCTION EVIDENCE

Every claim records how it was measured. A test cannot become production
evidence; a live URL cannot become customer evidence; a configured provider
cannot become a payment.

All rows measured on qevik-core-01 unless stated.

| ID | Capability | Claim | Evidence | Level | Timestamp | Revision | Notes |
|---|---|---|---|---|---|---|---|
| E-01 | C-01..C-03 | Real businesses discovered, audited and ranked | 329 `business_discovered`, 396 `website_audited`, 240 `website_verified`, 45 `prospect_scored` in `atlas_business_events` | PRODUCTION-VERIFIED | 2026-08-31 | 1a46afa | Counted directly from the production ledger |
| E-02 | C-04, C-07 | Every published address serves | 21 addresses fetched, 21 answered 200 | PRODUCTION-VERIFIED | 2026-08-30 | a7cd95b | `infra/verify_published.py` against the live hosts |
| E-03 | C-08 | The health check builds from real audits and refuses when it cannot | 33 built from 40 real audits, 7 refused for having no observations | PRODUCTION-VERIFIED | 2026-08-30 | 0f098b4 | `infra/verify_health_check.py` |
| E-04 | C-10 | A real weak-web-presence case recommends the health check | 28 of 40 real audits; 10 stored signals carry `offer-health-check` | PRODUCTION-VERIFIED | 2026-08-30 | 34a9088 | `infra/verify_health_check_recommended.py`, then a real verification pass wrote the signals |
| E-05 | C-09, C-17 | The whole chain runs: opportunity → approval → mission → worker → artefact → review → publication | `mission-e90201293964` and `mission-7920a1dd3d0c` completed; `worker-healthcheck` claimed both; two live URLs | PRODUCTION-VERIFIED | 2026-08-31 | 1a46afa | `infra/prove_health_check_chain.py`, `infra/publish_health_check.py` |
| E-06 | C-09 | Two health checks are live over HTTPS | `site-98cf44bff7fa44dc` 200/11,485b; `site-22fd58442af840e3` 200/11,281b; both survived a later deploy | PRODUCTION-VERIFIED | 2026-08-31 | 1a46afa | curl from the host |
| E-07 | C-11 | Outreach composes truthfully from a real published URL | Subject "What I found on Rise Up Plumbing Services Dubai's website"; state PREPARED; blocked only on `NO_SENDING_IDENTITY` | PRODUCTION-VERIFIED | 2026-08-31 | 1a46afa | Composed on the host from the real publication record |
| E-08 | C-24 | qevik.ai cannot send mail anybody will accept | MX, SPF, DMARC, DKIM all CONFIRMED_ABSENT, `unreadable=False` | PRODUCTION-VERIFIED | 2026-08-31 | 1a46afa | `deliverability.measure()` on the host. Independently confirms `70_EMAIL_INFRASTRUCTURE.md` of 2026-08-21 |
| E-09 | C-15..C-17 | Five workers, one agent each, all fresh | `worker-1`/self-check, `worker-delivery`/website-builder, `worker-healthcheck`/health-check, `worker-publish`/site-publisher, `worker-research`/researcher | PRODUCTION-VERIFIED | 2026-08-31 | 1a46afa | `mission.nodes.snapshots()` on the host |
| E-10 | C-22 | The action centre serves what its producers make | 12 open actions, 9 blocking, including `dns:qevik.ai` and both machines | PRODUCTION-VERIFIED | 2026-08-30 | 34a9088 | `infra/verify_action_centre.py`, which calls the route handler rather than the producers |
| E-11 | C-18 | Multi-GPU probing is deployed | Worker fingerprint changed to `9d2936ed0fe4` on deploy | DEPLOYMENT-VERIFIED | 2026-08-30 | — | **Not production-verified: there is no GPU on qevik-core-01 to probe.** Do not promote this row |
| E-12 | C-13 | — | — | — | — | — | **No evidence exists.** Zero messages sent. Nothing to record |
| E-13 | C-25 | A public audit records who asked, and the operator can see them | Wrote one row, read it back through `GET /api/missions/inbound`, counts correct, no personal data in the payload; synthetic row then removed | PRODUCTION-VERIFIED | 2026-08-31 | 5070e4a | The *mechanism* is verified. **Zero real inbound rows exist** — nobody has used the public audit. Do not read this as demand |

| E-14 | C-27a | An operator can approve an opportunity from the console | `data-approve-opportunity` and `/api/missions/deliver` present in the shipped console; the route resolves in the deployed router | PRODUCTION-VERIFIED | 2026-08-31 | 04c1e99 | The markup and route are verified. **No opportunity has been approved through the UI** — every approval this session was made from a script |
| E-15 | C-27, C-28 | The allowance ledger is durable, and nothing is metered | `QEVIK_STATE=/var/lib/qevik/control` is set for `qevik-control`, so the quota timeline resolves; `plan_of()` raises `NoPlan` for every tenant tried | PRODUCTION-VERIFIED | 2026-08-31 | 04c1e99 | Checked the suspicion that the ledger was in-memory. **It is not** — the env var is set and the file is simply absent because nothing has ever been spent |

## What is deliberately absent

There is no COMMERCIAL-VERIFIED row anywhere in this file, and there will not
be one until a real business receives something and answers. A published URL is
not a customer.
