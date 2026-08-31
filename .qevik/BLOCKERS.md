# QEVIK BLOCKERS

A blocker is scoped to the capability it actually blocks. Nothing here makes
the project blocked; every row names what can continue instead.

| ID | Blocker | Type | Affected capability | Dependency | Human action | Work continues elsewhere? | Resolution condition | Status |
|---|---|---|---|---|---|---|---|---|
| B-01 | qevik.ai has no MX, SPF, DMARC or DKIM | DNS | C-13, C-14 | Cloudflare zone | HA-001 | Yes — CRM, control plane, productization | `deliverability.measure()` reports MX, SPF and DMARC present. **Clearing this alone sends nothing — see B-13** | OPEN |
| B-02 | No mailbox and no SMTP settings | CREDENTIAL | C-13, C-14 | Mailbox provider | HA-002 | Yes — same | `EmailChannel.configured()` true, then a real inbox receipt with SPF/DKIM/DMARC passing | OPEN |
| B-03 | The ledger is loopback-only and there is no tailnet | NETWORK | C-19, C-20 | Tailscale, root on qevik-core-01 | HA-005 | Yes — everything except remote workers | A worker on another machine appears in Fabric | OPEN |
| B-04 | HP Z8 has never been provisioned | PHYSICAL | C-19 | Physical access | HA-003 | Yes | `atlas-z8` registers | OPEN |
| B-05 | Lenovo i9 has never been provisioned | PHYSICAL | C-20 | Physical access | HA-004 | Yes | `atlas-lenovo` registers | OPEN |
| B-06 | No media provider chosen or credentialed | DECISION + CREDENTIAL | C-30 | DQ-004 | none yet | Yes | A provider is chosen, then credentialed | OPEN |
| B-07 | No app-store developer accounts | ACCOUNT | C-31 | Apple, Google | none yet | Yes | Accounts exist and signing identities are held | OPEN |
| B-08 | No marketplace credentials | CREDENTIAL | C-33 | Amazon, Noon | none yet | Yes | Credentials exist | OPEN |
| B-09 | Computer-use lineage undecided | ARCHITECTURE | C-34 | DQ-002 | none | Yes | A lineage is chosen | OPEN |
| B-10 | Dormant Atlas surfaces undecided | PRODUCT_DECISION | C-35 | DQ-003 | none | Yes | Revive or retire is decided | OPEN |

| B-11 | No tenant is on a plan | PRODUCT_DECISION | C-27, C-28 | DQ-006 | none — it is a decision, not a credential | Yes — everything except metered work | An allowance is defined for Qevik's own operating tenant | OPEN |

| B-12 | 353 businesses have no sighting, so no discovery provenance | CODE | C-38 | The Places import path writes no sighting | none | Yes | Every business carries a sighting and a discovery state | OPEN |

| B-13 | No business has an email address | PRODUCT_DECISION | C-13 email sending | DQ-007 | none — a decision, not a credential | Yes | A source of addresses exists, or email outreach is dropped | OPEN |

## The rule this file exists to enforce

Ten open blockers and **none of them stops the next batch**. B-01 and B-02 hold
the commercial chain at its last step; B-03 to B-05 hold the fabric; B-06 to
B-10 hold factories nothing else depends on. CRM, control plane and
productization depend on none of them.
