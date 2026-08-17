# QEVIK SECURITY, SECRETS AND APPROVALS

## Principles

Qevik executes real-world actions, therefore security is part of the execution architecture.

## Secrets

Never store:
- API keys
- passwords
- SSH private keys
- session cookies
- payment credentials

in Git.

Use a secrets mechanism appropriate to the deployment.

Agents receive references or scoped access, not unnecessary global secrets.

## Agent permissions

Every execution should have:
- task identity
- project identity
- worker identity
- tool permissions
- timeout
- resource policy

## Risk classes

### Low risk
- read public website
- run tests
- build local project
- create local files

### Medium risk
- modify repository
- commit
- deploy to staging
- create cloud resources

### High risk
- production deletion
- purchases
- external messages
- payment actions
- critical DNS changes
- destructive production operations

High-risk actions require explicit approval unless a documented policy explicitly authorizes them.

## Audit

Record:
- who/what initiated action
- task ID
- timestamp
- tool
- target
- action
- result
- approval
- artifact/evidence

## Browser sessions

Use isolated profiles where possible.

Do not reuse a personal browser profile indiscriminately.

## Acceptance

Attempt a prohibited action and confirm it is blocked or approval-gated.
Perform an authorized action and confirm it is recorded in audit history.
