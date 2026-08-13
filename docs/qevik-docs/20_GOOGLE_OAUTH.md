# Google OAuth

## Status
IMPLEMENTED / LIVE TESTED

## Client
Desktop/installed OAuth client using localhost loopback with an ephemeral port.

The original Web application credential was incompatible with the implementation and was replaced with a Desktop client.

## Credential
`~/.qevik/credentials/google_client_secret.json`
Permissions: `600`
Outside repository.

## Scope
`https://www.googleapis.com/auth/gmail.send`

## App
Testing status. Test user configured.

## Security
Never commit, print, paste, or log the JSON/secret/token. Refresh tokens are durable credentials.

## Error handling
Safe structured fields such as status/reason may be surfaced. Free-text Google error bodies should not be surfaced because they can echo message/recipient content.

## Verified
A real Gmail send completed successfully.
