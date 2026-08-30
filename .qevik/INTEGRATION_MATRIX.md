# QEVIK INTEGRATION MATRIX

External dependencies and what is actually true about each. **No credential
values here.** Read from `atlas_kernel/integrations/registry.py` and the live
credential centre.

| Provider / system | Capability | Adapter | Credential (name only) | Configured | Tested | Production | Human action | Status |
|---|---|---|---|---|---|---|---|---|
| SMTP | C-13 outbound email | ✓ `outreach/channels.py` | `QEVIK_SMTP_HOST/_PORT/_USER/_PASSWORD/_FROM` | ✗ | ✗ | ✗ | HA-002 | BLOCKED |
| Cloudflare DNS | C-24 sending identity | — (no token; manual) | — | ✗ | measured | ✗ | HA-001 | BLOCKED |
| Google Places | C-01 contactable discovery | ✓ `opportunity/sources/google_places.py` | `QEVIK_GOOGLE_PLACES_API_KEY` | ✗ | **no probe, deliberately** | ✗ | credential | BLOCKED |
| Local filesystem | C-06 publication | ✓ `publication/targets` | `QEVIK_SITES_ROOT` (defaults to `/srv/sites`) | ✓ | ✓ | ✓ | none | CONNECTED |
| Anthropic | model work | ✓ | `QEVIK_ANTHROPIC_API_KEY` | ✗ | probe exists | ✗ | credential | BLOCKED |
| OpenAI | model work | ✓ | `QEVIK_OPENAI_API_KEY` | ✗ | probe exists | ✗ | credential | BLOCKED |
| Qwen / DashScope | model work | ✓ | `QEVIK_DASHSCOPE_API_KEY` | ✗ | probe exists | ✗ | credential | BLOCKED |
| Stripe | C-29 payment | ✗ `adapter_ready=False` | `QEVIK_STRIPE_SECRET_KEY` | ✗ | probe exists | ✗ | none yet | NOT BUILT |
| Google Search Console | SEO measurement | ✗ | — | ✗ | ✗ | ✗ | credential | NOT BUILT |
| Google Analytics | measurement | ✗ | — | ✗ | ✗ | ✗ | credential | NOT BUILT |
| Tailscale | C-19, C-20 fabric | — (operational) | account login | ✗ | ✗ | ✗ | HA-005 | BLOCKED |
| Amazon, Noon | C-33 | ✗ | — | ✗ | ✗ | ✗ | credential | NOT BUILT |
| Apple, Google Play | C-31 | ✗ | — | ✗ | ✗ | ✗ | account | NOT BUILT |
| Image / video / music | C-30 | ✗ | — | ✗ | ✗ | ✗ | DQ-004 first | NOT BUILT |

## Deliberately not probed

**Google Places has no probe and that is a decision, not a gap.** It bills every
authenticated request and offers no free listing endpoint, so a Test button
would charge for each press — and a button is pressed more than once. It is
verified instead by a discovery run returning businesses with a phone or a
website. The reason is written beside the probes in
`credentials/probes.py` so the next person to notice the gap finds the answer
rather than filling it.
