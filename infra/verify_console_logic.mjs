/* The console's render logic, exercised as code rather than by eye.
 *
 * Every visual defect in this project so far was found by screenshotting and
 * looking. That works, but it only ever covers the state that happened to be on
 * screen — and the two defects this file was written for were both states that
 * are awkward to produce on demand:
 *
 *   - a conversation whose mission exists but whose mission *fetch failed*,
 *     which rendered as "Drafting · No plan has been proposed yet". A failed
 *     read presented as a confirmed absence, on the screen a person uses to
 *     decide whether anything is happening.
 *   - a `closed` conversation, which offered a composer whose POST the API
 *     answers with 400.
 *
 * There is no DOM here and none is needed. The script is run in a `vm` context
 * with `document`/`window` stubbed to nothing useful; its bootstrap therefore
 * fails immediately, which is fine and expected — function declarations are
 * hoisted, so every function in the file is defined before the first statement
 * runs. The pure ones are then called directly.
 *
 *     node infra/verify_console_logic.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const HTML = readFileSync(join(ROOT, 'apps/control/src/index.html'), 'utf8');

const open = HTML.indexOf('<script>');
const shut = HTML.lastIndexOf('</script>');
if (open < 0 || shut < 0) { console.error('no <script> block found'); process.exit(1); }
const SOURCE = HTML.slice(open + '<script>'.length, shut);

/* Deliberately threadbare. Anything the script needs that is missing throws,
 * and a throw in the bootstrap is the expected outcome — it must not be treated
 * as a test failure, but it must also not be silently swallowed for the
 * *functions*, which are called below with no stubs at all. */
/* Threadbare, but complete enough that the script runs to its last line. It has
 * to: `STAGE` is a top-level `const`, and a top-level `const` in a script
 * creates a *lexical* binding rather than a property of the global object — so
 * an early throw leaves it unreachable even though hoisted functions survive.
 * Running to the end also means a genuine error anywhere in the file is caught
 * here instead of only in a browser. */
const node = () => new Proxy({}, {
  get(target, key) {
    if (key === 'classList') return { add() {}, remove() {}, toggle() {} };
    if (key === 'dataset' || key === 'style') return {};
    if (key === 'value' || key === 'textContent' || key === 'innerHTML') return '';
    if (key === 'disabled' || key === 'hidden') return false;
    if (key === Symbol.toPrimitive || key === 'then') return undefined;
    return () => node();
  },
  set: () => true,
});

const sandbox = {
  console,
  document: { querySelector: () => node(), querySelectorAll: () => [],
              getElementById: () => node(), addEventListener: () => {},
              body: node(), documentElement: node(), title: '' },
  localStorage: { getItem: () => '', setItem() {}, removeItem() {} },
  location: { hash: '', href: '', reload() {} },
  history: { replaceState() {}, pushState() {} },
  addEventListener: () => {},
  setInterval: () => 0, clearInterval: () => {}, setTimeout: () => 0,
  queueMicrotask: () => {},
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  fetch: async () => { throw new Error('the logic test makes no requests'); },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

const context = vm.createContext(sandbox);
/* Appended to the same script so the epilogue shares its lexical scope — the
 * only way to reach a top-level `const` from outside. */
const PROBE = ";globalThis.__under_test = { stageOf, whyItEnded, cost, STAGE, originOf, originChoice, discoveryLine };";
try {
  new vm.Script(SOURCE + PROBE, { filename: 'index.html' }).runInContext(context);
} catch (err) {
  console.error('the console script did not run to completion:', err.message);
  console.error(err.stack.split('\n').slice(0, 5).join('\n'));
  process.exit(1);
}

const PASS = [], FAIL = [];
function check(name, ok, detail = '') {
  (ok ? PASS : FAIL).push(name);
  console.log(`${ok ? '  ok  ' : '  FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
}
const { stageOf, whyItEnded, cost, STAGE, originOf, originChoice,
        discoveryLine } = sandbox.__under_test || {};

if (typeof stageOf !== 'function' || typeof whyItEnded !== 'function'
    || typeof cost !== 'function' || typeof originOf !== 'function'
    || typeof originChoice !== 'function'
    || typeof discoveryLine !== 'function' || !STAGE) {
  console.error('the functions under test were not defined — the script did not '
                + 'reach the end, or they were renamed');
  process.exit(1);
}

/* ---- stageOf: every conversation status, and the failed-read case --------- */

const conv = (status, extra = {}) => ({ status, ...extra });

check('an open conversation is drafting',
      stageOf(conv('open'), null) === 'drafting');

check('a proposed plan with steps waits for a person',
      stageOf(conv('plan_proposed', { plan: { steps: [{ title: 's' }], blockers: [] } }),
              null) === 'waiting');

check('a proposed plan that is only blockers is blocked',
      stageOf(conv('plan_proposed',
              { plan: { steps: [], blockers: [{ kind: 'BLOCKED_EXTERNAL_PROVIDER' }] } }),
              null) === 'blocked');

check('a rejected plan is declined',
      stageOf(conv('plan_rejected'), null) === 'declined');

/* The defect. `mission_created` with a null mission means the fetch failed —
 * `.catch(() => null)` — not that no mission exists. */
const unread = stageOf(conv('mission_created', { mission_id: 'm-1' }), null);
check('a mission whose status could not be read is not reported as drafting',
      unread !== 'drafting',
      `got ${unread}`);
check('...it is reported as unread', unread === 'unread');
check('...and its sentence does not claim nothing is happening',
      !/no plan has been proposed/i.test(STAGE[unread].says),
      JSON.stringify(STAGE[unread].says));

check('a closed conversation is closed, not drafting',
      stageOf(conv('closed'), null) === 'closed');

/* The mission, where one is readable, is what decides — not the conversation. */
for (const [status, expected] of [['complete', 'complete'], ['failed', 'failed'],
                                  ['cancelled', 'failed'], ['blocked', 'blocked'],
                                  ['awaiting_approval', 'waiting'],
                                  ['processing', 'running'], ['testing', 'running'],
                                  ['queued', 'running'], ['committing', 'running']]) {
  check(`a ${status} mission reads as ${expected}`,
        stageOf(conv('mission_created'), { status }) === expected);
}

check('every stage stageOf can return has an entry in STAGE',
      ['drafting', 'waiting', 'blocked', 'running', 'failed', 'complete',
       'declined', 'closed', 'unread'].every((s) => STAGE[s] && STAGE[s].word
                                                  && STAGE[s].says));

/* ---- whyItEnded ---------------------------------------------------------- */

check('a running mission has no failure summary',
      whyItEnded({ status: 'processing', note: 'claimed by w-1' }) === '');
check('a complete mission has no failure summary',
      whyItEnded({ status: 'complete', note: 'complete' }) === '');
check('no mission has no failure summary', whyItEnded(null) === '');

const why = whyItEnded({ status: 'failed',
  note: 'acceptance did not pass after 3 attempt(s): tests/test_x.py::test_y failed' });
check('a failed mission says why, from the recorded note',
      why.includes('tests/test_x.py::test_y'), why);

check('a cancelled mission says why',
      whyItEnded({ status: 'cancelled', note: 'released: operator cancelled' })
        .includes('operator cancelled'));

const silent = whyItEnded({ status: 'failed', note: '' });
check('a failure with no recorded reason says so rather than inventing one',
      silent.length > 0 && /no reason was recorded/i.test(silent), silent);

/* ---- cost: the rule that a missing cost is never zero -------------------- */

check('an unknown cost never renders a number',
      !/[0-9]/.test(cost(null, 'UNKNOWN')), cost(null, 'UNKNOWN'));
check('a zero cost that was actually measured still renders',
      /0/.test(cost(0, 'REPORTED')), cost(0, 'REPORTED'));
check('an undefined cost never renders "undefined"',
      !/undefined/.test(cost(undefined, 'UNKNOWN')), cost(undefined, 'UNKNOWN'));

/* ---- originOf: which repository is being approved --------------------- */

check('an unnamed origin reads as Qevik itself, not as "none"',
      /qevik/i.test(originOf('').word), originOf('').word);
check('...and says a person is required',
      /cannot run without you/i.test(originOf('').says));
check('the qevik origin is marked for attention',
      originOf('qevik').tone === 'warn');
check('an empty origin says nothing is at risk',
      /nothing is at risk/i.test(originOf('none').says), originOf('none').says);
check('...and is not marked for attention', originOf('none').tone === '');
check('a customer origin is named and says Qevik is untouched',
      originOf('acme-web').word === 'acme-web'
      && /untouched/i.test(originOf('acme-web').says));
check('a customer origin is never described as Qevik',
      !/qevik's own/i.test(originOf('acme-web').word));

/* ---- originChoice: the control an operator approves through ------------ */

const THREE = { origins: [
  { name: 'qevik', kind: 'qevik', modifies_qevik_itself: true, may_run_unattended: false },
  { name: 'none', kind: 'empty', modifies_qevik_itself: false, may_run_unattended: true },
  { name: 'acme-web', kind: 'customer', modifies_qevik_itself: false, may_run_unattended: false },
]};

const offered = originChoice(THREE);
check('every declared origin is offered',
      ['qevik', 'none', 'acme-web'].every((n) => offered.includes(`value="${n}"`)));
check('the choice is submitted as a key, never a path',
      !/\/(opt|var|home|Users|tmp)\//.test(offered),
      offered.match(/\/(opt|var|home|Users|tmp)\/[^"'<\s]*/)?.[0] || '');
check('the first option is preselected, so approving is never a blank choice',
      /value="qevik"[^>]*checked/.test(offered));
check('the Qevik option is marked before it is chosen, not after',
      /class="origin guarded"/.test(offered));
check('a customer option is not marked as guarded',
      !/acme-web[\s\S]{0,40}guarded/.test(offered));
check('each option carries the sentence explaining it',
      (offered.match(/class="note"/g) || []).length >= 3);

const single = originChoice({ origins: [THREE.origins[0]] });
check('a deployment with one origin states it rather than offering a choice',
      !single.includes('<input') && /Qevik/i.test(single), single.slice(0, 60));

const unreadable = originChoice({ origins: [] });
check('an unreadable list says what will happen instead of offering nothing',
      /could not be read/i.test(unreadable), unreadable.slice(0, 70));
check('...and names the origin that would be used',
      /Qevik/i.test(unreadable));
check('a null response is handled without throwing',
      typeof originChoice(null) === 'string');

/* ---- discoveryLine: the claim a row is allowed to make ------------------ */

const merelyOurs = discoveryLine({ name: 'X', source: 'google-places',
                                   claims_about_the_world: false });
check('a row new only to Qevik does not read as a new business',
      !/new business/i.test(merelyOurs.word + merelyOurs.says), merelyOurs.word);
check('...it says whose fact it is',
      /fact about Qevik/i.test(merelyOurs.says), merelyOurs.says);
check('...and names Qevik, not the source', /new to qevik/i.test(merelyOurs.word));

const evidenced = discoveryLine({ name: 'X', source: 'google-places',
                                  claims_about_the_world: true });
check('an evidenced row names the source it is new to',
      /google-places/.test(evidenced.word), evidenced.word);
check('...and still refuses to say new to the world',
      /not to the world/i.test(evidenced.says), evidenced.says);

/* The wording must follow the flag, not the state name — a client that read
 * the name would have to know which names are strong. */
const missingFlag = discoveryLine({ name: 'X', source: 'g',
                                    state: 'PROVEN_NEW_TO_SOURCE' });
check('a row with no flag is treated as the weaker claim',
      /new to qevik/i.test(missingFlag.word), missingFlag.word);

console.log(`\n${PASS.length} passed, ${FAIL.length} failed`);
process.exit(FAIL.length ? 1 : 0);
