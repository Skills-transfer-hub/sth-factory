'use strict';
const token = location.hash.slice(1);
if (token) history.replaceState(null, '', location.pathname);
const $ = selector => document.querySelector(selector);
const text = (tag, value, className) => {
  const el = document.createElement(tag);
  el.textContent = String(value);
  if (className) el.className = className;
  return el;
};
const message = value => {
  $('#message').textContent = value;
};
let selected = null, inspected = null, runRequest = 0, taskRequest = 0, snapshot = null,
  pageIndex = 0, motion = null;
const stations = new Map(), runButtons = new Map();
const motionMedia = matchMedia('(prefers-reduced-motion: reduce)');
const observer = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
  for (const item of entries) stations.get(item.target.dataset.task)?.player.setVisible(item.isIntersecting);
}) : null;

async function api(path) {
  const response = await fetch(path, {headers: {Authorization: 'Bearer ' + token}, cache: 'no-store'});
  const body = await response.json();
  if (!response.ok) throw Error(body.error || 'Lecture impossible');
  return body;
}

function motionLabel() {
  const active = motion === null ? !motionMedia.matches : motion;
  $('#motion-toggle').textContent = active ? 'Mettre les Buddies en pause' : 'Animer les Buddies au travail';
  $('#motion-toggle').setAttribute('aria-pressed', String(!active));
}

function clearStations() {
  for (const {card, player} of stations.values()) {
    observer?.unobserve(card);
    player.destroy();
    card.remove();
  }
  stations.clear();
}

function station(task) {
  const card = text('article', '', 'station');
  card.dataset.task = task.id;
  const head = text('div', '', 'station-head');
  head.append(
    text('span', String(task.index + 1).padStart(2, '0'), 'station-number'),
    text('h3', task.id, 'station-id')
  );
  const state = text('span', '', 'station-state');
  head.append(state);
  const stage = text('div', '', 'station-stage'), image = document.createElement('img');
  image.className = 'station-buddy';
  image.width = 144;
  image.height = 144;
  image.alt = 'Buddy — tâche ' + task.id;
  stage.append(image, text('div', '', 'station-bench'));
  const caption = text('p', '', 'station-caption'),
    deps = text('div', '', 'station-dependencies'),
    controls = text('div', '', 'station-controls'),
    button = text('button', 'Inspecter ' + task.id, 'station-select');
  button.type = 'button';
  button.addEventListener('click', () => showTask(selected, task.id));
  controls.append(button);
  card.append(head, stage, caption, deps, controls);
  const player = FactoryBuddyPlayer.create({image, caption, activityOnly: true});
  player.setMotion(motion);
  if (observer) player.setVisible(false);
  const entry = {card, player, state, deps, button, dependencyKey: null};
  stations.set(task.id, entry);
  observer?.observe(card);
  return entry;
}

function renderFloor() {
  const view = FactoryView.project(snapshot, {
    query: $('#task-search').value,
    filter: $('#task-state-filter').value,
    page: pageIndex
  });
  pageIndex = view.page;
  const keep = new Set(view.visible.map(t => t.id));
  for (const [id, entry] of stations) {
    if (!keep.has(id)) {
      observer?.unobserve(entry.card);
      entry.player.destroy();
      entry.card.remove();
      stations.delete(id);
    }
  }
  const labels = {
    total: 'Tâches', working: 'Au travail', waiting: 'En attente',
    success: 'Terminées', error: 'Erreurs', unknown: 'À vérifier'
  };
  const counts = Object.entries(labels).map(([key, label]) => {
    const el = text('div', '', 'count-tile');
    el.dataset.count = key;
    el.append(text('strong', view.counts[key], 'count-value'), text('span', label, 'count-label'));
    return el;
  });
  const countKey = JSON.stringify(view.counts);
  if ($('#factory-counts').dataset.key !== countKey) {
    $('#factory-counts').replaceChildren(...counts);
    $('#factory-counts').dataset.key = countKey;
  }
  const list = $('#tasks');
  view.visible.forEach((task, index) => {
    const entry = stations.get(task.id) || station(task);
    entry.card.dataset.state = task.state;
    entry.card.classList.toggle('is-selected', inspected?.task === task.id);
    entry.button.setAttribute('aria-pressed', String(inspected?.task === task.id));
    entry.state.textContent = task.state === 'success' ? 'Succès' : labels[task.state] || 'À vérifier';
    entry.player.observeState(task);
    const key = task.depends_on.join(',');
    if (entry.dependencyKey !== key) {
      entry.dependencyKey = key;
      entry.deps.replaceChildren(text('span', task.depends_on.length ? 'Dépend de :' : 'Sans dépendance'));
      for (const dep of task.depends_on) entry.deps.append(text('span', dep, 'dependency-chip'));
    }
    if (list.children[index] !== entry.card) list.insertBefore(entry.card, list.children[index] || null);
  });
  $('#floor-empty').hidden = view.visible.length > 0;
  if (!view.visible.length) $('#floor-empty').textContent = !selected ?
    'Sélectionner une exécution. Sans tâche, aucun Buddy sur le plateau.' : view.counts.total ?
      'Aucun poste ne correspond aux filtres.' : 'Cette exécution ne contient aucune tâche.';
  $('#task-page-prev').disabled = view.page === 0;
  $('#task-page-next').disabled = view.page + 1 >= view.pageCount;
  $('#task-page-label').textContent = view.filteredCount ?
    `${view.page*view.pageSize+1}–${view.page*view.pageSize+view.visible.length} sur ${view.filteredCount} postes · page ${view.page+1}/${view.pageCount}` :
    'Aucun poste affiché';
}

async function showTask(name, id) {
  const request = ++taskRequest;
  if (inspected?.run !== name || inspected?.task !== id) $('#details').replaceChildren(text('p', 'Chargement des preuves de ' + id + '…'));
  inspected = {run: name, task: id};
  $('#detail-title').textContent = 'Poste ' + id;
  renderFloor();
  try {
    const review = await api('/api/review?run=' + encodeURIComponent(name) + '&task=' + encodeURIComponent(id));
    if (request !== taskRequest || selected !== name || inspected?.task !== id) return;
    const task = review.tasks[id], details = $('#details');
    details.replaceChildren(text('p', 'Preuves locales ; les fichiers longs sont tronqués.'));
    if (task.patch) details.append(
      text('h4', 'Patch' + (task.patch.truncated ? ' — tronqué' : '')),
      text('pre', task.patch.text)
    );
    for (const [file, item] of Object.entries(task.logs || {})) details.append(
      text('h4', file + (item.truncated ? ' — fin du fichier' : '')),
      text('pre', item.text)
    );
  } catch (error) {
    if (request === taskRequest && selected === name && inspected?.task === id) message(error.message);
  }
}

function unavailable() {
  if (snapshot) {
    snapshot = {...snapshot, supervisor_active: false};
    renderFloor();
  }
}

async function showRun(name) {
  const request = ++runRequest;
  if (selected !== name) {
    taskRequest++;
    inspected = null;
    snapshot = null;
    pageIndex = 0;
    clearStations();
    $('#details').replaceChildren();
    $('#detail-title').textContent = 'Inspecter un poste';
  }
  selected = name;
  for (const [runName, button] of runButtons) {
    button.classList.toggle('is-selected', runName === name);
    button.setAttribute('aria-pressed', String(runName === name));
  }
  renderFloor();
  try {
    const run = await api('/api/status?run=' + encodeURIComponent(name));
    if (request !== runRequest || selected !== name) return;
    snapshot = run;
    $('#run-title').textContent = name;
    $('#summary').replaceChildren(
      text('p', 'État : ' + run.status, 'badge'),
      text('p', 'Commit : ' + (run.base || 'non disponible')),
      text('p', 'Source inchangée : ' + (run.source_unchanged === true ? 'oui' :
        run.source_unchanged === false ? 'non' : 'à vérifier'))
    );
    $('#events').textContent = (run.events || []).slice(-15).map(e => JSON.stringify(e)).join('\n') || 'Aucun événement disponible.';
    renderFloor();
    message((run.warnings || []).join(' · ') || 'États observés du moteur · actualisation toutes les 3 secondes.');
    if (inspected && Object.hasOwn(run.tasks, inspected.task)) await showTask(name, inspected.task);
  } catch (error) {
    if (request === runRequest && selected === name) {
      unavailable();
      message(error.message);
    }
  }
}

async function refresh() {
  if (!token) {
    message('Ouvrir le lien local complet fourni au démarrage, avec sa capacité après #.');
    return;
  }
  try {
    const result = await api('/api/runs'), keep = new Set(result.runs.map(r => r.name));
    for (const [name, button] of runButtons) if (!keep.has(name)) {
      button.remove();
      runButtons.delete(name);
    }
    for (const run of result.runs) {
      let button = runButtons.get(run.name);
      if (!button) {
        button = text('button', '', 'run');
        button.addEventListener('click', () => showRun(run.name));
        runButtons.set(run.name, button);
        $('#runs').append(button);
      }
      button.textContent = run.name + ' · ' + run.status;
      button.setAttribute('aria-pressed', String(selected === run.name));
    }
    if (selected) await showRun(selected);
    else message(result.runs.length ? 'Choisir une exécution.' : 'Aucune exécution inspectable dans ce dossier.');
  } catch (error) {
    unavailable();
    message(error.message);
  }
}

$('#refresh').addEventListener('click', refresh);
for (const id of ['#task-search', '#task-state-filter']) $(id).addEventListener(
  id === '#task-search' ? 'input' : 'change',
  () => {
    pageIndex = 0;
    renderFloor();
  }
);
$('#task-page-prev').addEventListener('click', () => {
  pageIndex--;
  renderFloor();
});
$('#task-page-next').addEventListener('click', () => {
  pageIndex++;
  renderFloor();
});
$('#motion-toggle').addEventListener('click', () => {
  motion = !(motion === null ? !motionMedia.matches : motion);
  for (const entry of stations.values()) entry.player.setMotion(motion);
  motionLabel();
});
motionMedia.addEventListener('change', () => {
  motion = null;
  for (const entry of stations.values()) entry.player.setMotion(null);
  motionLabel();
});
window.addEventListener('pagehide', () => {
  clearStations();
  observer?.disconnect();
});
motionLabel();
renderFloor();
refresh();
setInterval(refresh, 3000);
