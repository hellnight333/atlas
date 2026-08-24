# QEVIK CREDENTIAL VAULT — AUTONOMOUS IMPLEMENTATION DIRECTIVE

## Objective

Build a permanent, secure Credential & Connection Center inside `app.qevik.ai`.

The purpose is to eliminate the current failure mode where an API key exists only in a Claude/Codex session, terminal environment, or chat and disappears when a new session starts.

The user must be able to securely configure and manage:

- Claude / Anthropic
- OpenAI / Codex
- Qwen
- DeepSeek
- Other OpenAI-compatible models
- Stripe
- Cloudflare
- Google Search Console
- Google Analytics
- SMTP / email
- Social/media providers
- Marketplace providers
- Future integrations

**Do not ask the user to paste production credentials into chat, Git, Markdown, source code, reports, or logs.**

---

## 1. Core architecture

First inspect and reuse the existing:

- `integrations/registry.py`
- `Connection`
- `LLMProvider`
- `AnthropicProvider`
- `OpenAICompatibleProvider`
- `ModelRegistry`
- `QuotaLedger`
- `Mission`
- `AgentInvocation`
- `HumanAction`
- tenancy/authentication
- existing customer/control-plane APIs

Do not create competing versions of:

- model registry
- integration registry
- quota ledger
- mission registry
- tenant system

Create/extend one credential boundary, for example:

```text
credentials/
  models.py
  service.py
  vault.py
  providers.py
  api.py
  redaction.py
  tests/
```

The exact location may follow the existing architecture.

The business/application layer should use a `CredentialReference`, not raw secrets.

---

## 2. Secret storage

Never store plaintext secrets in ordinary business tables.

Never put credentials in:

- Git
- `.md`
- reports
- BusinessEvent payloads
- Mission reports
- chat history
- logs
- browser localStorage
- telemetry
- exception messages

Development may use an OS secure store:

- macOS Keychain
- Linux Secret Service/keyring
- Windows Credential Manager

`.env` may exist only for local bootstrap, must be gitignored, and must never be committed or returned through APIs.

Production must use encrypted secret storage. Build a provider abstraction so a KMS/secret-manager implementation can later replace the local implementation without changing the business layer.

The encryption/master key must live outside the encrypted credential records.

---

## 3. Vault lock

Add a Credential Vault lock protected by a PIN or separate password.

Requirements:

- never store the PIN itself
- strong password hashing for server validation
- rate-limit failed attempts
- temporary lockout after repeated failures
- auto-lock after inactivity
- explicit Lock / Unlock
- Change PIN
- security events without secrets
- short-lived unlock session/token where appropriate

Do not use the PIN as the only server-side encryption boundary.

---

## 4. `app.qevik.ai` UI

Create a polished control-center interface:

```text
Mission Control
Roadmap
Missions
Chat / Planner
Businesses
Integrations
  AI Models
  Search & Analytics
  Cloudflare
  Payments
  Email
  Social / Media
Credential Vault
Reports / History
```

Credential cards should show only safe metadata:

```text
Qwen
CONNECTED
Last tested: ...
Model: ...
Usage: ...
Estimated cost: ...

[Test] [Edit] [Rotate] [Disable]
```

Never show the complete secret after saving.

Mask credentials:

```text
sk-••••••••••••26c
```

or provider-appropriate equivalent.

---

## 5. Add connection workflow

The user should be able to:

```text
+ Add Connection
       ↓
Choose provider
       ↓
Choose credential type
       ↓
Enter secret
       ↓
Optional configuration
       ↓
Test connection
       ↓
Save securely
```

Examples:

### Qwen

- API key
- base URL if required
- default model
- optional budget

### Stripe

- secret key
- publishable key
- webhook signing secret

### SMTP

- host
- port
- username
- password
- TLS mode

### Cloudflare

- API token
- account identifier

Provider-specific schemas are allowed, but storage remains behind the common vault boundary.

---

## 6. Connection status

Use explicit statuses:

```text
CONNECTED
NOT_CONFIGURED
INVALID_CREDENTIAL
INSUFFICIENT_PERMISSION
RATE_LIMITED
NETWORK_ERROR
PROVIDER_ERROR
DISABLED
PENDING_CREDENTIAL
```

Never expose the secret in an error.

Example:

```text
Qwen connection failed.
Reason: INVALID_CREDENTIAL
[Re-enter credential]
```

---

## 7. Existing Qwen key

Do not ask the user to paste the previous Qwen key into chat again.

Treat it as `UNKNOWN / NOT RELIABLY PERSISTED` unless it already exists in a legitimate secure runtime store.

Do not search shell history, chat transcripts, Git history, or arbitrary files for the key.

If it is not safely persisted:

```text
Qwen → ACTION REQUIRED
```

The user will enter it through the new Credential Center.

---

## 8. AI model registry

Extend the existing `ModelRegistry`.

Support:

```text
Claude
Codex/OpenAI
Qwen
DeepSeek
OpenAI-compatible providers
Local models
Future providers
```

Model configuration should include:

```text
provider
model_id
capabilities
context_window
input_cost
output_cost
credential_reference
enabled
```

Allow separate model selection for:

```text
Planning
Implementation
Review
Summarization
Research
Cheap/background work
```

Example:

```text
Planner      → Claude
Implementer  → Codex
Reviewer     → Qwen
Cheap tasks  → DeepSeek
```

No source-code changes should be required to change the selected model.

---

## 9. Cost tracking

For every model invocation record:

```text
provider
model
mission_id
role
input_tokens
output_tokens
estimated_cost
currency
timestamp
```

Use the existing cost/model registry rather than creating a second pricing system.

If actual provider billing data is unavailable, label it:

```text
Estimated usage cost
```

Never represent estimates as invoices.

Mission Control should show:

```text
Today
This month
By provider
By model
By mission
```

---

## 10. Budget controls

Reuse:

```text
QuotaLedger
Credits / Plans
estimated_units
Mission
AgentInvocation
```

Do not create another quota system.

Support:

- per mission limit
- daily limit
- monthly limit
- per provider limit
- per model limit

When exhausted:

```text
BLOCKED — budget exhausted
```

Never silently switch to an uncontrolled provider.

---

## 11. Human Action / blocker integration

Use the existing `HumanAction`, `ActionKind`, `controlplane/actions.py`, and `integrations/registry.py`.

Missing credentials become actions:

```text
ACTION REQUIRED

Qwen
Needed by: Coding Agent
Reason: selected model is not configured

[Connect Qwen]
```

Likewise:

```text
Stripe
Needed by: Billing
Required: Stripe secret key

[Connect Stripe]
```

Do not create another action-center system.

---

## 12. Mission Control

Show credential health globally:

```text
AI
Claude       CONNECTED
Qwen         CONNECTED
OpenAI       ACTION REQUIRED
DeepSeek     ACTION REQUIRED

Infrastructure
Cloudflare   ACTION REQUIRED

Search
GSC          ACTION REQUIRED
Analytics    ACTION REQUIRED

Payments
Stripe       ACTION REQUIRED
```

A mission should show its dependency:

```text
#103 SEO audit
Status: PENDING_CREDENTIAL
Needs: Search Console
[Configure]
```

---

## 13. Chat → Plan → Execute

The future chat system must resolve configured credentials by reference.

If the user says:

> use Qwen for the cheap reviewer

the planner resolves the configured Qwen credential.

If Qwen is missing:

```text
PLAN READY

1. Configure Qwen
2. Run reviewer
```

with:

```text
[Open Credential Center]
```

Never ask the user to paste the API key into chat.

---

## 14. Persistence requirement

A new Claude/Codex session must be able to discover:

```text
provider: Qwen
reference: qwen/default
status: CONNECTED
```

without depending on the previous Claude chat.

The worker resolves the credential at runtime.

The secret itself must not be stored in the agent's memory.

This directly fixes the current problem.

---

## 15. Rotation / disable

Support:

```text
Rotate
Disable
Enable
Delete reference
```

Rotation:

```text
new secret
   ↓
test
   ↓
atomic replacement
   ↓
old reference no longer active
```

Do not destroy the existing credential before the replacement passes validation.

Deleting a Qevik reference must not falsely claim that the provider key has been revoked externally.

---

## 16. Audit

Record safe events:

```text
Credential connected
Credential tested
Credential rotated
Credential disabled
Credential enabled
Vault unlocked
Vault locked
Failed unlock
```

Never record:

- API key
- password
- secret
- access token
- refresh token

Cross-tenant credential access must return absence, consistent with existing tenancy rules.

---

## 17. Security tests

Add negative tests proving:

1. secrets cannot be serialized into normal API responses
2. secrets cannot appear in BusinessEvents
3. secrets cannot appear in Mission reports
4. secrets cannot appear in audit events
5. secrets cannot appear in error messages
6. GET integration never returns the raw secret
7. cross-tenant credential access fails
8. repeated bad PIN attempts are rate-limited/locked
9. disabled credentials cannot be used
10. failed rotation preserves the working credential
11. secrets cannot be committed to Git
12. worker does not log secrets
13. `.env` cannot accidentally enter the repository
14. missing credentials cannot silently fall back to another tenant's credential

---

## 18. Acceptance test

The implementation is complete only when this scenario is supported:

```text
1. Open app.qevik.ai
2. Open Credential Center
3. Unlock vault
4. Add Qwen
5. Enter key
6. Test
7. Save
8. Close browser
9. Start a new Claude/Codex session
10. Start a mission requiring Qwen
11. Worker resolves Qwen through CredentialReference
12. Mission runs
13. Cost is recorded
14. Report is persisted
15. Reopen app
16. Qwen still shows CONNECTED
17. Full key is never displayed
```

Also test:

```text
User A adds Stripe
User B cannot access it
Stripe is disabled
Billing refuses to use it
UI shows ACTION REQUIRED
```

---

## 19. Autonomous execution

Do NOT stop unrelated work because a credential is unavailable.

For external dependencies use:

```text
IMPLEMENTED
PENDING_CREDENTIAL
```

not:

```text
STOP
```

Continue with all unblocked roadmap work after the credential system is implemented, including:

- multi-page websites
- media
- P3/P4 work
- P5/P6/P7 adapters
- mission persistence
- reports
- Mission Control
- Qevik self-use
- existing-business re-evaluation
- other unblocked work in the authoritative state documents

---

## 20. Final documentation

At completion, update:

```text
docs/qevik-docs/autonomous/STATE.md
docs/qevik-docs/autonomous/MASTER_EXECUTION_STATE.md
docs/qevik-docs/autonomous/ROADMAP_RECONCILIATION.md
```

and create a persistent report under:

```text
docs/qevik-docs/autonomous/reports/
```

Report:

- vault architecture
- storage implementation
- providers
- UI/API routes
- vault lock
- ModelRegistry integration
- QuotaLedger integration
- Mission integration
- cost tracking
- security tests
- cross-tenant tests
- pending credentials
- remaining blockers
- commit SHAs
- test count
- ruff
- mypy
- working tree
- push status

Never include credential values.

---

## 21. Git

Commit cleanly.

Do not push automatically unless current execution policy explicitly authorizes pushing.

Report:

```text
HEAD:
origin/main:
ahead/behind:
working tree:
```

Never commit credentials.

---

# FINAL AUTONOMOUS INSTRUCTION

Implement this specification now.

Do not return a plan only.

Do not stop because Qwen, Claude, Stripe, Cloudflare, Google, SMTP, or another credential is missing.

Build the secure Credential Center and mark missing integrations `PENDING_CREDENTIAL`.

After this is complete, continue with the next unblocked roadmap work.

Do not give intermediate reports.

At the end, provide ONE consolidated implementation report.

The intended architecture is:

```text
                  QEVIK CONTROL PLANE
                         │
        ┌────────────────┼────────────────┐
        │                │                │
     ROADMAP          MISSIONS       CREDENTIALS
        │                │                │
        │          Plan → Execute     Secure Vault
        │                │                │
        └────────── Model Registry ───────┘
                         │
              Claude / Codex / Qwen
                 / DeepSeek / ...
                         │
                      Workers
                         │
                 Persistent Reports
                         │
                  Mission History
```

The user enters a credential once in Qevik. Future autonomous sessions and workers use its secure reference without depending on the previous Claude chat.

**START NOW.**
