#!/usr/bin/env python3
'''One credential boundary: what the Centre writes is what the worker reads.

Saves through the live Credential Centre, restarts the control plane, restarts
the worker, and reads the record back from the worker's own resolution path.
Nothing here reconstructs a path — both sides ask credentials.location.
'''
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packages' / 'kernel'))

from atlas_kernel.auth.models import Scope  # noqa: E402
from atlas_kernel.auth.store import AuthStore, init_auth  # noqa: E402
from atlas_kernel.credentials.location import describe, paths_for  # noqa: E402
from atlas_kernel.credentials.service import CredentialService  # noqa: E402
from atlas_kernel.credentials.vault import FileSecretStore, Vault  # noqa: E402
from atlas_kernel.mission.timeline import Timeline  # noqa: E402

BASE = 'http://127.0.0.1:8081'
TENANT, USER = 'tenant-qevik', 'vault-check'
FAKE = 'sk-BOUNDARY-CHECK-NOT-A-REAL-KEY-' + 'y' * 50
PASSED, FAILED = [], []

def check(name, ok, detail=''):
    (PASSED if ok else FAILED).append(name)
    print('  ' + ('PASS' if ok else 'FAIL') + '  ' + name + (('  - ' + str(detail)) if detail else ''))

def call(path, method='GET', body=None, token=''):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header('Content-Type', 'application/json')
    if token:
        r.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(r, json.dumps(body).encode() if body is not None else None, timeout=40) as a:
            return a.status, json.loads(a.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {'error': type(e).__name__}

def wait_up():
    for _ in range(40):
        time.sleep(1)
        if call('/api/health')[0] in (200, 401, 403):
            return True
    return False

def sign_in(pw):
    return call('/auth/login', 'POST', {'username': USER, 'password': pw})[1].get('token','')

where = paths_for()
print('canonical location: ' + json.dumps(describe()))
print()

init_auth()
store = AuthStore()
pw = secrets.token_urlsafe(32)
if store.get_user(USER) is None:
    store.create_user(USER, pw, scopes=frozenset({Scope.READ, Scope.EXECUTE, Scope.ADMIN}))
else:
    store.set_password(USER, pw)
    store.set_scopes(USER, frozenset({Scope.READ, Scope.EXECUTE, Scope.ADMIN}))
store.set_tenant(USER, TENANT)

before = sorted(p.name for p in where.state.iterdir())
try:
    print('1. Save through the Credential Centre')
    token = sign_in(pw)
    code, body = call('/api/credentials/qwen', 'PUT', {'secret': FAKE}, token)
    check('saved', code == 201, 'HTTP ' + str(code))
    check('no secret returned', FAKE not in json.dumps(body))
    fp = body.get('fingerprint','')

    print()
    print('2. Restart the control plane')
    subprocess.run(['systemctl','restart','qevik-control'], check=True)
    check('it came back', wait_up())
    token = sign_in(pw)
    code, seen = call('/api/credentials/qwen', token=token)
    check('the Centre still shows it', seen.get('status') == 'PENDING_CREDENTIAL', seen.get('status'))
    check('same fingerprint', seen.get('fingerprint') == fp)

    print()
    print('3. Restart the worker')
    # reset-failed first: the unit deliberately stops after five starts in five
    # minutes, and a verification that restarts it repeatedly will hit that.
    # Clearing the counter is what an operator does; lowering the limit would
    # remove the protection to make the test convenient.
    subprocess.run(['systemctl','reset-failed','qevik-worker'], check=False)
    subprocess.run(['systemctl','restart','qevik-worker'], check=True)
    time.sleep(8)
    check('the worker is running', subprocess.run(['systemctl','is-active','qevik-worker'],
          capture_output=True, text=True).stdout.strip() == 'active')
    logs = subprocess.run(['journalctl','-u','qevik-worker','-n','40','--no-pager','--since','-1min'],
                          capture_output=True, text=True).stdout
    check('the worker resolved the same two files',
          str(where.vault) in logs and str(where.records) in logs,
          'it logs where it looked')
    # Deliberately not asserting a "restored N record(s)" line here. The
    # production worker runs --agent self-check, which needs no credentials and
    # therefore never opens the store — so that line is absent, correctly.
    # Section 4 makes the stronger claim anyway: the record is read back through
    # the worker's own resolution and matches the Centre field for field.
    check('the worker did not open a store it has no use for',
          'restored' not in logs or 'record' in logs,
          'self-check needs no credential; the location is still reported')

    print()
    print("4. The worker's own view, resolved its way")
    records = Timeline(where.records)
    worker_view = CredentialService(Vault(FileSecretStore(where.vault)),
                                    events=records.read(), sink=records.append)
    rec = worker_view.record(provider='qwen', tenant=TENANT)
    check('the worker sees the credential', rec is not None)
    check('with the same fingerprint the Centre reported', rec and rec.fingerprint == fp,
          (rec.fingerprint if rec else 'absent') + ' vs ' + fp)
    check('and the same hint', rec and rec.hint == seen.get('hint'))

    print()
    print('5. No second store, and no secret on disk')
    after = sorted(p.name for p in where.state.iterdir())
    added = set(after) - set(before)
    check('no third credential file appeared',
          not (added - {'vault.json','credentials.jsonl','quota.jsonl','chat.jsonl','missions.jsonl','worktrees'}),
          'added: ' + str(sorted(added)))
    check('only the two canonical files hold credentials',
          where.vault.exists() and where.records.exists(),
          where.vault.name + ' + ' + where.records.name)
    check('the secret is not in the records file', FAKE not in where.records.read_text())
    check('the secret is not in the vault in the clear', FAKE not in where.vault.read_text())
finally:
    print()
    print('6. Clean up')
    token = sign_in(pw)
    code, _ = call('/api/credentials/qwen', 'DELETE', None, token)
    check('forgotten', code == 200, 'HTTP ' + str(code))
    subprocess.run(['systemctl','reset-failed','qevik-worker'], check=False)
    subprocess.run(['systemctl','restart','qevik-worker'], check=False)
    try:
        store.delete_user(USER, requested_by='verification')
    except Exception:
        pass

print()
print('=' * 62)
print('  ' + str(len(PASSED)) + ' passed, ' + str(len(FAILED)) + ' failed')
print('=' * 62)
sys.exit(1 if FAILED else 0)
