# GitHub Workflow

GitHub access from this ChatGPT session has not been reliable enough to be the primary workflow.

## New operating model
Markdown documentation is portable project memory.
User can put it into Git, commit/push, and let Claude/OpenClaw use the same files.

## Never commit
- OAuth JSON
- client/access/refresh tokens
- service account private keys
- secrets in `.env`

Before push:
- `git status`
- inspect diff
- check ignored secrets
- run relevant tests

Claude can push implementation changes to the existing repository.
