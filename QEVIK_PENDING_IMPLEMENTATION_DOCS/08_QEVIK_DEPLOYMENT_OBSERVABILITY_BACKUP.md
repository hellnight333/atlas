# QEVIK DEPLOYMENT, OBSERVABILITY AND BACKUP

## Production principles

Qevik Core must be recoverable independently of any laptop.

## Services

Document and supervise:
- API
- worker scheduler
- execution service
- PostgreSQL
- browser worker
- other required services

## Health

Every critical service should expose a health signal.

Track:
- process health
- disk
- memory
- CPU
- database connectivity
- worker availability
- queue depth
- failed tasks

## Logs

Centralize or consistently collect:
- application logs
- task logs
- browser logs
- deployment logs
- worker logs
- security/audit logs

## Backups

At minimum:
- PostgreSQL backup
- configuration backup
- repository remains in Git
- artifact backup strategy
- restore procedure

A backup is not considered valid until restore is tested.

## Deployment

Use reproducible deployment procedures.

Avoid manual server configuration that cannot be recreated.

## Recovery acceptance

Demonstrate:
1. clean/known server state
2. restore database
3. deploy Qevik
4. start services
5. health checks green
6. existing task/project data accessible

## SSH

Do not rely on an SSH terminal staying open for execution.

SSH is an administration channel only.
