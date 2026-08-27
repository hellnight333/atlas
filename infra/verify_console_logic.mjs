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
const PROBE = ";globalThis.__under_test = { stageOf, whyItEnded, cost, STAGE, originOf, originChoice, discoveryLine, opportunityCard, deliveryCard, wireReview, API };";
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
        discoveryLine, opportunityCard, deliveryCard,
        wireReview } = sandbox.__under_test || {};

if (typeof stageOf !== 'function' || typeof whyItEnded !== 'function'
    || typeof cost !== 'function' || typeof originOf !== 'function'
    || typeof originChoice !== 'function'
    || typeof discoveryLine !== 'function'
    || typeof opportunityCard !== 'function' || !STAGE) {
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

/* ---- opportunityCard: four parts, and an honest worth ------------------ */

const OPP = {
  id: 'sig-1', kind: 'missing_service', source: 'openstreetmap',
  score: 0.598, detected_at: '2026-08-27T04:15:00+00:00',
  business_id: 'b-1', needs_approval: false,
  evidence_fingerprints: ['8c23957ade3bb410'],
  value: { amount: null, status: 'UNKNOWN' },
  detail: {
    observations: [{ statement: 'openstreetmap records no website for Marina Dental.' }],
    inferences: [{ statement: 'The business may have no website, or may have one this source does not record.',
                   confidence: 0.35, is_an_inference: true,
                   would_be_wrong_if: 'the business has a website openstreetmap does not list' }],
    actions: [{ statement: 'Check whether this business has a website.' }],
  },
};

const card = opportunityCard(OPP);
check('the observation leads, as the headline',
      card.indexOf('records no website') < card.indexOf('may have no website'),
      'the inference came first');
check('the inference is labelled as an inference on screen',
      /Inference/.test(card));
check('...and the observation is not', !/>Observation</.test(card));
check('the falsifier is shown, so a reader can disagree',
      /Wrong if/.test(card));
check('the evidence fingerprint is shown', /8c23957ade/.test(card));
check('UNKNOWN worth never renders as a number',
      !/Worth[\s\S]{0,120}>0</.test(card), 'a zero appeared under Worth');
check('...it renders as UNKNOWN', /UNKNOWN/.test(card));

const gated = opportunityCard({ ...OPP, needs_approval: true });
check('an action needing a person says so', /needs you/.test(gated));
check('...and one that does not, does not',
      !/needs you/.test(card));

const bare = opportunityCard({ id: 'x', kind: 'new_business', detail: {} });
check('a row with no inference does not invent one',
      typeof bare === 'string' && !/Inference/.test(bare));

/* ---- the artefact a reviewer is shown ------------------------------------
 *
 * Everything here is a customer's business name, a customer's generated markup
 * or a reviewer's own note, rendered in the page that holds the operator's
 * session token. The two properties worth proving are that data is escaped on
 * the way into the card, and that the artefact body never reaches the DOM as
 * HTML at all. */

const HOSTILE = '<img src=x onerror=alert(1)>';
const DELIVERY = {
  mission_id: 'mission-1', signal_id: 'sig-1',
  approved_scope: 'offer-website: performance',
  approved_by: HOSTILE, evidence_fingerprints: ['abc1234567def'],
  recipe: 'deliver-website', agent_id: 'website-builder',
  tools: ['website-generator'], origin_name: 'none',
  workspace: '/var/lib/qevik/scratch/mission-1/repo', branch: 'mission/mission-1',
  commit: '0123456789abcdef0123456789abcdef01234567',
  files: [{ path: 'artefact/index.html', name: HOSTILE, size: 12, blob: 'b1' }],
  provenance: { addresses: [HOSTILE], not_published_for_want_of_a_source: ['email'] },
  reviews: [],
};

const delivery = deliveryCard(DELIVERY);
check('the delivery card renders', typeof delivery === 'string' && delivery.length > 0);
check('a hostile filename is escaped, not embedded',
      !/<img /.test(delivery) && /&lt;img/.test(delivery),
      'a raw <img tag reached the card');
check('...the payload survives as characters, which is correct and harmless',
      /onerror=alert\(1\)&gt;/.test(delivery),
      'the text is shown; only the angle brackets are neutralised');
check('a hostile approver name is escaped the same way',
      (delivery.match(/<img /g) || []).length === 0);
check('a hostile provenance string is escaped',
      !/<img src=x/.test(delivery));
check('the chain is on screen: opportunity, scope, recipe, agent, tool',
      /sig-1/.test(delivery) && /offer-website: performance/.test(delivery)
      && /deliver-website/.test(delivery) && /website-builder/.test(delivery)
      && /website-generator/.test(delivery));
check('...and the workspace, branch and commit a reviewer would otherwise ssh for',
      /scratch\/mission-1\/repo/.test(delivery)
      && /mission\/mission-1/.test(delivery) && /0123456789ab/.test(delivery));
check('a role with no network tool says so',
      /could not publish or contact anyone/.test(delivery));
check('NEGATIVE CONTROL: a role with one does not claim that',
      !/could not publish or contact anyone/.test(
        deliveryCard({ ...DELIVERY, tools: ['http-fetch'] })));
check('an unreviewed artefact says nobody has decided',
      /not reviewed/.test(delivery));
check('...and a reviewed one shows the decision and who made it',
      /accepted/.test(deliveryCard({ ...DELIVERY,
        reviews: [{ decision: 'accepted', actor: 'ayoub', at: '', note: '' }] })));
const livePublished = deliveryCard({ ...DELIVERY,
  reviews: [{ decision: 'accepted', actor: 'ayoub', at: '', note: '' }],
  published: [{ url: 'https://sites.qevik.ai/site-1/', site_id: 'site-1',
                commit: '0123456789abcdef', at: '2026-08-27T11:18:00Z' }] });
check('a published artefact says so', /published/.test(livePublished));
check('...showing the address and the commit that went out',
      /sites\.qevik\.ai\/site-1/.test(livePublished)
      && /0123456789ab/.test(livePublished));
check('...and the publish control is gone',
      !/data-publish/.test(livePublished),
      'republishing is a new decision, not a button left over from the last one');
check('NEGATIVE CONTROL: an accepted, unpublished one offers it',
      /data-publish/.test(deliveryCard({ ...DELIVERY,
        reviews: [{ decision: 'accepted', actor: 'a', at: '', note: '' }] })));
check('...and an unreviewed one does not',
      !/data-publish/.test(delivery));

check('accepting is described as recording, not publishing',
      /does not publish/.test(delivery) && /does not contact anyone/.test(delivery));

/* The one that matters: which DOM property the artefact body is written to.
 * A recorder rather than a source grep — a test that greps for `textContent`
 * passes when somebody leaves the word in a comment and assigns innerHTML. */
const written = [];
const pane = { set textContent(v) { written.push(['textContent', v]); },
               get textContent() { return ''; },
               set innerHTML(v) { written.push(['innerHTML', v]); },
               hidden: true };
let handler = null;
const button = { dataset: { file: 'artefact/index.html' }, disabled: false,
                 textContent: '',
                 addEventListener: (_e, fn) => { handler = fn; } };
context.document.querySelectorAll = (sel) =>
  (sel === '[data-file]' ? [button] : []);
context.document.querySelector = (sel) =>
  (sel === '[data-artefact]' ? pane : null);
const ARTEFACT_BODY = '<script>window.__ran = true</script>';
sandbox.__under_test.API.get = async () => ({ text: ARTEFACT_BODY });
sandbox.__under_test.API.post = async () => ({});

wireReview('mission-1', DELIVERY);
check('the file button is wired', typeof handler === 'function');
await handler();
check('the artefact body is written with textContent',
      written.some(([property]) => property === 'textContent'),
      JSON.stringify(written.map(([p]) => p)));
check('...and innerHTML is never used for it',
      !written.some(([property]) => property === 'innerHTML'),
      'customer markup reached the DOM as HTML');
check('...so the script tag arrives as characters, not as a tag',
      written.some(([property, value]) => property === 'textContent'
        && value === ARTEFACT_BODY),
      `the pane received ${JSON.stringify(written.map(([, v]) => String(v).slice(0, 40)))}`);
check('nothing executed in the operator session',
      context.window.__ran === undefined);

console.log(`\n${PASS.length} passed, ${FAIL.length} failed`);
process.exit(FAIL.length ? 1 : 0);
