'use strict';
(function (root) {
  // Only task identifiers accepted by the factory, never HTML or commands.
  const identifier = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
  const captions = Object.freeze({
    pending: 'Tâche en attente', not_started: 'Tâche non démarrée',
    running: 'Tâche en cours', succeeded: 'Tâche terminée avec succès',
    failed: 'Tâche en échec', timed_out: 'Délai dépassé', cancelled: 'Tâche annulée',
    interrupted: 'Tâche interrompue', blocked: 'Tâche bloquée', unknown: 'État à vérifier'
  });
  const states = new Set(['waiting', 'working', 'success', 'error', 'unknown']);
  const failures = new Set(['failed', 'timed_out', 'cancelled', 'interrupted', 'blocked']);
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const owns = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  const validID = value => typeof value === 'string' && identifier.test(value);
  const dependencies = value => Array.isArray(value) ? [...new Set(value.filter(validID))] : [];

  function durationLabel(timing, liveAllowed = false) {
    const seconds = object(timing) ? timing.duration_seconds : null;
    if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0 ||
        (timing.live === true && !liveAllowed)) return 'Durée indisponible';
    const value = seconds < 60 ? seconds.toFixed(1).replace('.', ',') + ' s' :
      seconds < 3600 ? `${Math.floor(seconds / 60)} min ${Math.floor(seconds % 60)} s` :
        `${Math.floor(seconds / 3600)} h ${Math.floor(seconds % 3600 / 60)} min`;
    return (timing.live === true ? 'Écoulé : ' : 'Durée : ') + value;
  }

  function project(snapshot, options = {}) {
    const run = object(snapshot) ? snapshot : {};
    const settings = object(options) ? options : {};
    const observed = object(run.tasks) ? run.tasks : {};
    const plan = object(run.plan) && Array.isArray(run.plan.tasks) ? run.plan.tasks : [];
    const ordered = new Map();
    for (const task of plan) {
      if (object(task) && validID(task.id) && !ordered.has(task.id)) ordered.set(task.id, task);
    }
    for (const id of Object.keys(observed)) {
      if (validID(id) && !ordered.has(id)) ordered.set(id, null);
    }
    const tasks = [];
    const counts = {total: 0, waiting: 0, working: 0, success: 0, error: 0, unknown: 0};
    for (const [id, planned] of ordered) {
      const exists = owns(observed, id);
      const actual = exists && object(observed[id]) ? observed[id] : {};
      const raw = exists ? actual.status : 'not_started';
      const status = typeof raw === 'string' && owns(captions, raw) ? raw : 'unknown';
      let state = 'unknown';
      let caption = captions[status];
      if (status === 'pending' || status === 'not_started') state = 'waiting';
      else if (status === 'succeeded') state = 'success';
      else if (failures.has(status)) state = 'error';
      else if (status === 'running') {
        if (run.status === 'running' && run.supervisor_active === true) state = 'working';
        else caption = 'Activité non vérifiée ; état à vérifier';
      }
      const deps = owns(actual, 'depends_on') ? actual.depends_on : planned && planned.depends_on;
      const record = {id, status, state, caption, depends_on: dependencies(deps), index: tasks.length,
        duration: durationLabel(actual.timing, state === 'working')};
      tasks.push(record);
      counts.total += 1;
      counts[state] += 1;
    }
    const query = typeof settings.query === 'string' ? settings.query.trim().toLowerCase().slice(0, 512) : '';
    const filter = states.has(settings.filter) ? settings.filter : 'all';
    const filtered = tasks.filter(task => (filter === 'all' || task.state === filter) &&
      (!query || [task.id, task.status, task.caption, ...task.depends_on].join(' ').toLowerCase().includes(query)));
    const pageSize = typeof settings.pageSize === 'number' && Number.isFinite(settings.pageSize) ?
      Math.max(1, Math.min(24, Math.floor(settings.pageSize))) : 24;
    const pageCount = Math.ceil(filtered.length / pageSize);
    const requestedPage = typeof settings.page === 'number' && Number.isFinite(settings.page) ? Math.floor(settings.page) : 0;
    const page = Math.max(0, Math.min(Math.max(0, pageCount - 1), requestedPage));
    return {tasks, visible: filtered.slice(page * pageSize, (page + 1) * pageSize), counts,
      page, pageCount, filteredCount: filtered.length, pageSize};
  }
  const api = Object.freeze({project, durationLabel});
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FactoryView = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
