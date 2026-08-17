# QEVIK SYSTEM ACCEPTANCE TESTS

## Purpose

Prevent "looks implemented" from being confused with "works."

## A. Core

- [ ] clean database initialization
- [ ] database restore
- [ ] API health
- [ ] worker health
- [ ] test suite
- [ ] lint/typecheck/build

## B. Coding execution

- [ ] create project
- [ ] agent edits files
- [ ] tests run
- [ ] failure diagnosed
- [ ] fix applied
- [ ] commit created
- [ ] push performed only when authorized

## C. Browser

- [ ] open public site
- [ ] extract content
- [ ] screenshot
- [ ] interact with form
- [ ] download/upload
- [ ] authenticated workflow using authorized profile
- [ ] crawl multiple pages
- [ ] detect browser failure

## D. Deployment

- [ ] build
- [ ] deploy
- [ ] HTTPS
- [ ] public URL
- [ ] browser verification
- [ ] deployment record
- [ ] failure recovery

## E. Iran

- [ ] Iran HTTP check
- [ ] Iran browser check
- [ ] screenshot
- [ ] result provenance says Iran
- [ ] compare against Hetzner

## F. Persistence

- [ ] close SSH
- [ ] close browser
- [ ] reconnect
- [ ] task continues
- [ ] logs preserved
- [ ] artifacts preserved

## G. Mobile

- [ ] login from phone
- [ ] view task
- [ ] approve action
- [ ] view logs
- [ ] view artifact
- [ ] open deployment

## H. Website Factory

Natural-language request → public verified website.

## I. App Factory

Natural-language request → tested application artifact/deployment.

## J. Content Factory

Natural-language request → generated/assembled artifact → quality verification.

## K. Security

- [ ] unauthorized tool blocked
- [ ] high-risk action approval
- [ ] secret not present in Git
- [ ] audit trail
- [ ] worker authentication

## Final release gate

Do not call the system production-ready until critical tests are green or explicitly waived with a documented reason.
