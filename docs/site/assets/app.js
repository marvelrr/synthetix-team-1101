'use strict';

const DIMENSIONS = [
  ['appeal', 'Appeal'], ['usefulness', 'Usefulness'], ['ease_of_use', 'Ease of use'],
  ['trust', 'Trust'], ['intention_to_use', 'Intention to use']
];
const STEPS = ['product', 'profiles', 'results'];
let evidence = null;
const byId = id => document.getElementById(id);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined && text !== null) element.textContent = String(text);
  if (className) element.className = className;
  return element;
};
const clear = element => element.replaceChildren();
const text = (id, value) => { byId(id).textContent = String(value ?? 'Not recorded'); };
const list = (items, className) => {
  const element = node('ul', undefined, className);
  for (const item of items || []) element.append(node('li', item));
  return element;
};
const titleCase = value => String(value).replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase());
const profileName = (user, index) => user.segment || `Profile ${index + 1}`;
const recordedDate = value => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value || 'date not supplied') :
    `${new Intl.DateTimeFormat('en-GB', {day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Hong_Kong'}).format(date)} HKT`;
};
const share = (numerator, denominator) => denominator > 0
  ? `${Math.round(numerator / denominator * 100)}% (${numerator} of ${denominator} rated)`
  : 'Not assessable (0 eligible ratings)';

function showStep(step, focus = false) {
  if (!STEPS.includes(step) || !evidence) return;
  for (const name of STEPS) {
    const active = name === step;
    const button = byId(`tab-${name}`);
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
    byId(`panel-${name}`).hidden = !active;
  }
  if (focus) {
    byId(`tab-${step}`).focus({preventScroll: true});
    byId('demo').scrollIntoView({behavior: 'smooth', block: 'start'});
  }
}

function renderProfiles(data) {
  const grid = byId('profiles-grid');
  clear(grid);
  data.users.forEach((user, index) => {
    const card = node('article', undefined, 'profile-card');
    card.append(node('div', `PROFILE ${String(index + 1).padStart(2, '0')}`, 'profile-index'));
    card.append(node('h3', profileName(user, index)));
    const entries = Object.entries(user.profile || {});
    const priorityEntries = entries.filter(([key]) => /priority|review stance/i.test(key));
    const summaryEntries = priorityEntries.length ? priorityEntries.slice(0, 2) : entries.slice(0, 3);
    card.append(node('p', summaryEntries.map(([key, value]) => `${titleCase(key)}: ${value}`).join(' · ') || 'See the recorded attributes below.'));
    const details = node('details');
    details.append(node('summary', 'Attributes and authored assumptions'));
    const attributes = node('dl', undefined, 'attributes');
    for (const [key, value] of entries) {
      const pair = node('div');
      pair.append(node('dt', titleCase(key)), node('dd', value));
      attributes.append(pair);
    }
    details.append(attributes);
    if (user.authored_assumptions?.length) {
      details.append(node('h4', 'Authored assumptions'), list(user.authored_assumptions));
    }
    if (user.sourced_facts?.length) {
      details.append(node('h4', 'Supplied sourced facts'), list(user.sourced_facts));
    }
    details.append(node('p', `Generator: ${user.generator_version || 'not recorded'}`, 'quiet'));
    card.append(details);
    grid.append(card);
  });
}

function renderCoverage(aggregate) {
  const coverage = aggregate.coverage || {};
  const counts = coverage.status_counts || {};
  const root = byId('coverage');
  clear(root);
  [['Requested', coverage.requested], ['Completed', coverage.completed], ['Failed', counts.failed ?? coverage.failed], ['Cancelled', counts.cancelled ?? coverage.cancelled]].forEach(([label, value]) => {
    const metric = node('div');
    metric.append(node('div', Number.isInteger(value) ? value : '—', 'metric-value'), node('div', label, 'metric-label'));
    root.append(metric);
  });
  byId('interim').hidden = !coverage.interim;
}

function renderFindings(data) {
  const root = byId('findings');
  clear(root);
  text('summary-method', data.provenance.summary_method || 'Themes supplied with the recorded evidence; unique supporting profiles counted in code.');
  if (!data.findings?.length) {
    root.append(node('p', 'No combined concern groups were published for this run. Inspect the independent reviews below.', 'empty'));
    return;
  }
  const evaluations = new Map(data.evaluations.map(item => [item.user_id, item]));
  const users = new Map(data.users.map((item, index) => [item.user_id, {item, index}]));
  for (const finding of data.findings) {
    const card = node('article', undefined, 'finding');
    const heading = node('header');
    heading.append(node('h4', finding.theme));
    const n = new Set(finding.supporting_user_ids || []).size;
    heading.append(node('span', `${n} of ${finding.eligible_denominator} eligible profiles`, 'support'));
    card.append(heading, node('span', finding.severity, 'severity'));
    const details = node('details');
    details.append(node('summary', 'Inspect supporting evidence'));
    const refs = new Set(finding.evidence_refs || []);
    const items = node('ul');
    for (const userId of new Set(finding.supporting_user_ids || [])) {
      const entry = node('li', undefined, 'evidence-problem');
      const user = users.get(userId);
      const button = node('button', user ? profileName(user.item, user.index) : userId, 'evidence-link');
      button.type = 'button';
      button.addEventListener('click', () => {
        const review = byId(`review-${user?.index}`);
        if (review) { review.open = true; review.scrollIntoView({behavior: 'smooth', block: 'center'}); }
      });
      entry.append(button);
      const topic = data.topic_index?.find(item => item.topic === finding.theme);
      const indexedEvidence = topic?.evidence?.filter(item => item.user_id === userId);
      const matchingProblems = indexedEvidence?.length ? indexedEvidence :
        evaluations.get(userId)?.problems?.filter(problem => (problem.task_id || null) === (finding.task_id || null)) || [];
      if (matchingProblems.length) {
        entry.append(node('div', indexedEvidence?.length ? 'Exact saved statements matched by the published topic index:' : 'Saved problem statements from this profile (full list for the relevant task or concept review):', 'quiet'));
        entry.append(list(matchingProblems.map(problem => problem.text)));
      }
      const ref = `${userId}:${finding.task_id || 'evaluation'}`;
      if (refs.has(ref)) entry.append(node('div', `Evidence: ${ref}`, 'review-id'));
      items.append(entry);
    }
    details.append(items);
    card.append(details);
    root.append(card);
  }
}

function renderRatings(aggregate) {
  const signals = byId('signals');
  clear(signals);
  [['appeal_signal', 'Positive synthetic appeal rating'], ['adoption_interest_signal', 'Positive synthetic intention-to-use rating']].forEach(([key, label]) => {
    const metric = aggregate[key] || {};
    const card = node('div', undefined, 'signal');
    card.append(node('strong', share(metric.numerator, metric.denominator)), node('p', `${label} (4 or 5 out of 5)`));
    signals.append(card);
  });
  const root = byId('ratings');
  clear(root);
  for (const [key, label] of DIMENSIONS) {
    const metric = aggregate.ratings?.[key] || {};
    const row = node('div', undefined, 'rating-row');
    row.append(node('span', label, 'rating-name'));
    const bars = node('div', undefined, 'rating-bars');
    bars.setAttribute('role', 'img');
    const binDescriptions = [];
    for (let score = 1; score <= 5; score++) {
      const n = metric.counts?.[score] || 0;
      binDescriptions.push(`${score} out of 5: ${n} profiles`);
      const bin = node('div', undefined, 'rating-bin');
      const fill = node('div', undefined, 'rating-fill');
      fill.style.height = `${metric.eligible ? n / metric.eligible * 100 : 0}%`;
      bin.append(fill, node('span', `${score}: ${n}`));
      bars.append(bin);
    }
    bars.setAttribute('aria-label', binDescriptions.join('; '));
    row.append(bars);
    const mean = typeof metric.mean === 'number' ? `${metric.mean.toFixed(1)}/5 mean` : 'Not assessable';
    row.append(node('span', `${mean} · ${metric.eligible || 0} eligible · ${metric.not_assessable || 0} not assessable · ${metric.missing || 0} missing`, 'rating-mean'));
    root.append(row);
  }
}

function addReviewList(body, heading, items) {
  if (items?.length) body.append(node('h4', heading), list(items));
}

function renderReviews(data) {
  const root = byId('individual-reviews');
  clear(root);
  const evals = new Map(data.evaluations.map(item => [item.user_id, item]));
  data.users.forEach((user, index) => {
    const evaluation = evals.get(user.user_id);
    const review = node('details', undefined, 'review');
    review.id = `review-${index}`;
    review.append(node('summary', `${String(index + 1).padStart(2, '0')} · ${profileName(user, index)}`));
    const body = node('div', undefined, 'review-body');
    if (!evaluation) {
      body.append(node('p', `No saved evaluation. Profile status: ${user.status}.`));
      if (user.failure_reason) body.append(node('p', user.failure_reason));
    } else {
      const ratings = node('div', undefined, 'review-rating-grid');
      for (const [key, label] of DIMENSIONS) {
        const rating = evaluation.ratings?.[key];
        const cell = node('div', undefined, 'review-rating');
        cell.append(node('span', label));
        cell.append(node('strong', rating?.score != null ? `${rating.score}/5` : 'Not assessable'));
        if (rating?.not_assessable_reason) cell.append(node('div', rating.not_assessable_reason, 'na-reason'));
        ratings.append(cell);
      }
      body.append(ratings, node('h4', 'Rating reasons'), node('p', evaluation.rating_reasons, 'quote'));
      addReviewList(body, 'Strengths', evaluation.strengths);
      if (evaluation.problems?.length) {
        body.append(node('h4', 'Problems raised'));
        const problems = node('ul');
        for (const problem of evaluation.problems) {
          const item = node('li');
          item.append(node('span', problem.severity, 'severity'), node('span', problem.text));
          if (problem.task_id) item.append(node('span', ` (${problem.task_id})`, 'quiet'));
          problems.append(item);
        }
        body.append(problems);
      }
      addReviewList(body, 'Suggested improvements', evaluation.suggestions);
      if (evaluation.pricing_feedback) body.append(node('h4', 'Pricing feedback'), node('p', evaluation.pricing_feedback));
    }
    body.append(node('p', `Profile ID: ${user.user_id}`, 'review-id'));
    review.append(body);
    root.append(review);
  });
}

function renderProvenance(data) {
  const p = data.provenance;
  const usage = data.usage || [];
  const total = key => usage.reduce((sum, item) => sum + (Number(item[key]) || 0), 0);
  const allCostsKnown = usage.length > 0 && usage.every(item => typeof item.cost_hkd === 'number');
  const entries = [
    ['Run ID', p.run_id], ['Recorded (Hong Kong)', recordedDate(p.recorded_at_hkt)], ['Model', p.model],
    ['Mode', p.mode], ['Wall time', typeof p.wall_seconds === 'number' ? `${p.wall_seconds.toFixed(1)} seconds` : 'Not recorded'],
    ['LLM calls', usage.length ? total('llm_calls') : 'Not recorded'], ['Input tokens', usage.length ? total('input_tokens') : 'Not recorded'], ['Output tokens', usage.length ? total('output_tokens') : 'Not recorded'],
    ['Recorded API cost', allCostsKnown ? `HK$${total('cost_hkd').toFixed(4)}` : 'Unknown — pricing unavailable'],
    ['Local model inference', p.local_inference === false ? 'None' : 'Not recorded'],
    ['New browser visits', p.browser_visits ?? 'Not recorded'], ['Material SHA-256', p.source_material_sha256],
    ['Aggregation', p.summary_method]
  ];
  const root = byId('provenance-details');
  clear(root);
  entries.forEach(([key, value]) => root.append(node('dt', key), node('dd', value ?? 'Not recorded')));
}

function validate(data) {
  if (data?.schema_version !== '1.0' || !data.config || !data.provenance || !data.aggregate ||
      !Array.isArray(data.users) || !Array.isArray(data.evaluations) || data.users.length < 1) {
    throw new Error('The published evidence schema is incomplete.');
  }
  const ids = new Set(data.users.map(user => user.user_id));
  if (ids.size !== data.users.length) throw new Error('Duplicate profile IDs in evidence.');
  for (const evaluation of data.evaluations) {
    if (!ids.has(evaluation.user_id)) throw new Error('Evaluation has no matching profile.');
  }
  return data;
}

async function loadEvidence() {
  byId('load-error').hidden = true;
  text('provenance-text', 'Loading the published evidence…');
  try {
    const response = await fetch('assets/refillhk-five-persona.json', {cache: 'no-cache'});
    if (!response.ok) throw new Error('Recorded data not available.');
    const data = validate(await response.json());
    evidence = data;
    text('product-name', data.config.product_name);
    text('value-proposition', data.config.value_proposition);
    text('concept-material', data.config.concept_material);
    const p = data.provenance;
    text('provenance-text', `Recorded ${recordedDate(p.recorded_at_hkt)} · ${data.users.length} authored AI profiles · ${p.model || 'model not supplied'}. This walkthrough replays saved outputs; it does not generate a fresh review.`);
    if (p.mode === 'concept') text('mode-explanation', 'A concept review of the exact material below. No product navigation, form submission or browser tasks were performed in this run.');
    renderProfiles(data);
    renderCoverage(data.aggregate);
    renderFindings(data);
    renderRatings(data.aggregate);
    renderReviews(data);
    renderProvenance(data);
    byId('demo').hidden = false;
  } catch (error) {
    evidence = null;
    byId('demo').hidden = true;
    byId('load-error').hidden = false;
    text('provenance-text', 'Recorded evidence unavailable. No results are being simulated on this page.');
  }
}

async function loadDeployment() {
  try {
    const response = await fetch('assets/deployment.json', {cache: 'no-cache'});
    if (!response.ok) return;
    const data = await response.json();
    if (!data.live_app_url) return;
    const url = new URL(data.live_app_url);
    if (url.protocol !== 'https:' || /^(localhost|127\.|0\.0\.0\.0|\[::1\])/.test(url.hostname)) return;
    byId('live-link').href = url.href;
    byId('live-link').hidden = false;
    text('live-status', 'Open the separately hosted application to submit content and request a fresh review. This recorded showcase itself makes no model requests.');
  } catch (_) { /* No live deployment is claimed unless valid configuration exists. */ }
}

document.querySelectorAll('[data-step]').forEach(button => {
  button.addEventListener('click', () => showStep(button.dataset.step));
  button.addEventListener('keydown', event => {
    const current = STEPS.indexOf(button.dataset.step);
    let index;
    if (event.key === 'ArrowRight') index = (current + 1) % STEPS.length;
    if (event.key === 'ArrowLeft') index = (current + STEPS.length - 1) % STEPS.length;
    if (event.key === 'Home') index = 0;
    if (event.key === 'End') index = STEPS.length - 1;
    if (index !== undefined) { event.preventDefault(); showStep(STEPS[index], true); }
  });
});
document.querySelectorAll('.next-step').forEach(button => button.addEventListener('click', () => showStep(button.dataset.next, true)));
byId('start-tour').addEventListener('click', () => {
  if (evidence) showStep('product', true);
  else byId('load-error').scrollIntoView({behavior: 'smooth', block: 'center'});
});
byId('replay').addEventListener('click', () => showStep('product', true));
byId('retry').addEventListener('click', loadEvidence);
loadEvidence();
loadDeployment();
