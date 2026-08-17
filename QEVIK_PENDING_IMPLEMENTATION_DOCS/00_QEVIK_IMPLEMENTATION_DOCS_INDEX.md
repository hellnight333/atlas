# QEVIK IMPLEMENTATION DOCUMENT SET

Use these documents together with the existing repository documentation.

## Order

1. `01_QEVIK_MASTER_EXECUTION_PLAN.md`
   - master implementation sequence
   - phases
   - definition of done

2. `02_QEVIK_BROWSER_AGENT_AND_COWORK_ARCHITECTURE.md`
   - browser/coding agent execution model
   - Claude Code/Cowork/OpenClaw adapter concept

3. `03_QEVIK_IRAN_WORKER_SPEC.md`
   - genuine Iran-origin browsing/crawling/verification

4. `04_QEVIK_WEBSITE_FACTORY_SPEC.md`
   - complete website creation/deployment workflow

5. `05_QEVIK_APP_GAME_CONTENT_FACTORIES.md`
   - app/game/content execution workflows

6. `06_QEVIK_CONTROL_PLANE_AND_MOBILE.md`
   - phone/browser control surface

7. `07_QEVIK_SECURITY_SECRETS_APPROVALS.md`
   - permissions, secrets, audit and approvals

8. `08_QEVIK_DEPLOYMENT_OBSERVABILITY_BACKUP.md`
   - production operation, recovery and backups

9. `09_QEVIK_PUBLIC_WEBSITE_AND_COMMERCIALIZATION.md`
   - Qevik's own product website and commercial layer

10. `10_QEVIK_ACCEPTANCE_TESTS.md`
   - final executable acceptance checklist

## Important

These documents supplement, rather than replace:
- existing Qevik architecture
- PROJECT_STATE
- ROADMAP
- decisions/ADRs
- current infrastructure specification
- autonomous execution architecture already provided

Claude Code must inspect the existing repository and reconcile these documents with the current implementation before changing code.

If two documents conflict, the repository's current authoritative project-state/decision documents take precedence until the conflict is explicitly resolved.
