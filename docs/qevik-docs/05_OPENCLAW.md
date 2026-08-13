# Qevik — OpenClaw Plan

## Purpose
OpenClaw is planned as Qevik's self-hosted operator/control layer.

## Preferred host
**P520** as dedicated operator machine.
Z8 remains primarily for heavy AI/rendering.

## Proposed topology
User → ChatGPT/Claude → OpenClaw → Browser / Terminal / Git / Cloud / External services

P520 = operator/control
Z8 = heavy AI/rendering
Other workstation = media/compute as assigned
Mac = personal workstation

## Initial host plan
- dedicated OS on P520
- dedicated OpenClaw OS user
- local Gateway initially
- isolated agent browser
- project-only credentials
- no personal password manager
- no unrestricted personal browser session

## Browser
Use OpenClaw's dedicated managed browser profile for automation. Do not use the personal daily-driver profile by default.

## Credentials
Prefer dedicated project accounts for GitHub, Google, Cloudflare, registrar and infrastructure.

## Network
Keep Gateway local/loopback initially. If remote access is needed, use authenticated private access/tailnet and firewall rules. Never expose an unauthenticated Gateway publicly.

## Sandboxing
Use sandboxing where practical. Treat host execution/elevated access as an explicit trust decision.

## Security audit
After configuration:
`openclaw security audit`
Before exposure:
`openclaw security audit --deep`

## First milestone
1. P520 OS/user
2. Install OpenClaw
3. Local Gateway
4. Isolated browser
5. Git/Qevik workspace
6. Claude/OpenAI provider access
7. VS Code/terminal workflow
8. Security audit
9. First controlled task
10. Add cloud/browser credentials only afterward

## Important boundary
OpenClaw must not silently send prospecting email, deploy production systems, delete data, change billing, rotate important credentials, or purchase services without the defined approval policy.
