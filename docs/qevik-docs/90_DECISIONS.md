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
