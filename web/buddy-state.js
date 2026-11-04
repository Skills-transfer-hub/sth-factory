'use strict';
(function (root) {
  const failures = new Set(['failed', 'timed_out', 'cancelled', 'interrupted', 'blocked']);
  const pending = new Set(['pending', 'not_started']);
  const result = (state, caption) => Object.freeze({state, caption, progress: null});
  function observedState(run) {
    if (run === null || run === undefined) return result('waiting', 'Aucune exécution sélectionnée');
    if (typeof run !== 'object' || Array.isArray(run)) return result('unknown', 'État indisponible');
    const taskStates = Object.values(run.tasks || {}).map(task => task && task.status);
    if (run.status === 'succeeded') {
      if (taskStates.some(status => status !== 'succeeded')) return result('unknown', 'États incohérents ; résultat à vérifier');
      return result('success', 'Exécution terminée avec succès');
    }
    if (run.status === 'running') return result('working', 'Exécution en cours');
    if (failures.has(run.status)) {
      const captions = {failed: 'Exécution en échec', timed_out: 'Délai dépassé', cancelled: 'Exécution annulée',
                        interrupted: 'Exécution interrompue', blocked: 'Exécution bloquée'};
      return result('error', captions[run.status]);
    }
    if (pending.has(run.status)) return result('waiting', 'Exécution en attente');
    return result('unknown', 'État indisponible');
  }
  const api = Object.freeze({observedState});
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FactoryBuddyState = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
