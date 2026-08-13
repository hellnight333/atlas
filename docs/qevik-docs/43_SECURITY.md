# Security

Principles:
1. Secrets are not source code.
2. Secrets are not logs.
3. Secrets are not chat messages.
4. Credentials stay outside repositories.
5. Connections have explicit ownership.
6. Customer credentials are never used for Qevik outreach.
7. High-impact actions require approval.
8. Agents get minimum required permissions.
9. Browser automation uses isolated profiles.
10. Significant actions should be auditable.

Google credential:
`~/.qevik/credentials/google_client_secret.json`
permissions `600`

OpenClaw should use a dedicated trust boundary, isolated browser and security audit before exposure.
