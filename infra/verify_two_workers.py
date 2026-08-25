#!/usr/bin/env python3
'''Two workers, one mission. Exactly one may run it.

The claim primitive was proven with eight racing processes. This proves the
*worker* actually uses it: two real mission workers are started at the same
instant against the same queued mission, and the mission must be executed once.

Without the atomic claim both would fold the same timeline, both would see a
queued mission, and both would run it — producing two commits of the same change
with no error anywhere.
'''
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packages' / 'kernel'))

from atlas_kernel.mission import service  # noqa: E402
from atlas_kernel.mission.adapter import SELF_CHECK_STEPS, build  # noqa: E402
from atlas_kernel.mission.models import MissionStatus  # noqa: E402
from atlas_kernel.mission.timeline import Timeline  # noqa: E402

TENANT = 'tenant-race'
DSN = os.environ['QEVIK_CLAIMS_DSN']
PASSED, FAILED = [], []

def check(name, ok, detail=''):
    (PASSED if ok else FAILED).append(name)
    print('  ' + ('PASS' if ok else 'FAIL') + '  ' + name + (('  - ' + str(detail)) if detail else ''))

work = Path(tempfile.mkdtemp(prefix='qevik-race-'))
timeline = Timeline(work / 'missions.jsonl')

mission, event = service.create(tenant=TENANT, title='Race: only one worker may run me',
                                requested_by='verification')
timeline.append(event)
planned = build('self-check', SELF_CHECK_STEPS).plan(mission.title)
mission, event = service.transition(mission, MissionStatus.PLANNING, tenant=TENANT, actor='verification')
timeline.append(event)
mission, event = service.attach_plan(mission, planned, tenant=TENANT)
timeline.append(event)
mission, event = service.transition(mission, MissionStatus.QUEUED, tenant=TENANT, actor='verification', note='approved')
timeline.append(event)
print('mission ' + mission.id + ' is queued')

def worker(name):
    return subprocess.Popen(
        [sys.executable, str(ROOT / 'infra' / 'mission_worker.py'),
         '--timeline', str(timeline.path), '--tenant', TENANT, '--name', name,
         '--repository', str(ROOT), '--worktrees', str(work / name),
         '--reports', str(work / 'reports'), '--agent', 'self-check', '--once',
         '--claims-dsn', DSN, '--require-atomic-claims'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

print()
print('starting two workers at the same instant')
a, b = worker('worker-a'), worker('worker-b')
out_a, out_b = a.communicate(timeout=600)[0], b.communicate(timeout=600)[0]

check('both workers exited cleanly', a.returncode == 0 and b.returncode == 0,
      'a=' + str(a.returncode) + ' b=' + str(b.returncode))

claimed = [n for n, o in (('worker-a', out_a), ('worker-b', out_b)) if 'claiming ' + mission.id in o]
check('EXACTLY ONE worker claimed the mission', len(claimed) == 1, 'claimed by ' + str(claimed))
# The property, not one mechanism. A loser is correct whether it lost the
# atomic claim ('went to another worker') or never saw the mission because the
# winner had already moved it out of QUEUED. What would be wrong is both
# running it, and that is what the claim count below establishes.
loser = [o for n, o in (('worker-a', out_a), ('worker-b', out_b)) if n not in claimed]
check('the other did not run it, by whichever mechanism stopped it first',
      len(loser) == 1 and 'finished as' not in loser[0],
      'stood down at the claim' if 'went to another worker' in loser[0]
      else 'never saw it queued')
check('both reported Postgres-backed claiming',
      out_a.count('multi-worker safe') + out_b.count('multi-worker safe') == 2)

rows = service.fold(timeline.read(), tenant=TENANT)
row = [r for r in rows if r['mission_id'] == mission.id][0]
check('the mission completed once', row['status'] == 'complete', row['status'])
check('with exactly one commit', len(row.get('commits') or []) == 1, str(row.get('commits')))

processing = [json.loads(line)['detail'] for line in open(timeline.path)]
claims = [d for d in processing if d.get('status') == 'processing']
check('and was claimed exactly once on the timeline', len(claims) == 1,
      str(len(claims)) + ' processing transitions')

print()
print('=' * 62)
print('  ' + str(len(PASSED)) + ' passed, ' + str(len(FAILED)) + ' failed')
print('=' * 62)
sys.exit(1 if FAILED else 0)
