# Gmail Integration

## Status
IMPLEMENTED / REAL SEND VERIFIED

A real Gmail message was sent through the complete M014 path.

## Pipeline
Approval → fingerprint verification → suppression → cooldown → Gmail send

## Verified safeguards
- duplicate same-business send blocked by 90-day cooldown
- edited-after-approval proposal blocked by fingerprint mismatch
- suppressed address blocked

## Channel
`GmailChannel` implements the existing `OutreachChannel` protocol.

Business safety remains in `OutreachService`; channels should not duplicate it.

## Errors
- 401: reconnect
- 403: inspect structured reason
- 429: backoff
- do not expose free-text error bodies

## Sender
Current test sender: `qevikos@gmail.com`
Long-term use a domain-based business sender and build reputation gradually.

## Testing
Gmail/credential/YouTube tests are passing; full suite remains blocked by PostgreSQL.
