'use strict';
(function (root) {
  const base = '/buddy-3d/161b1278/';
  const sequences = {
    waiting: ['ok', 80],
    working: ['work', 48],
    success: ['done', 38],
    error: ['error', 30],
    unknown: ['ok', 80]
  };

  function create({image, caption, button = null, playback = null, activityOnly = false}) {
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    let state = 'waiting', index = 0, clock = 0, frameRequest = null, userMotion = null;
    let assetFailed = false, playing = false, generation = 0, pendingFrame = false,
      visible = true, destroyed = false;
    const allowedMotion = () => userMotion === null ? !media.matches : userMotion;

    function cancelPending() {
      generation++;
      pendingFrame = false;
    }

    function showFrame(next = index) {
      if (assetFailed || pendingFrame || destroyed) return;
      const request = generation, sequence = sequences[state][0], candidate = new Image();
      pendingFrame = true;
      candidate.src = base + sequence + '/' + String(next).padStart(4, '0') + '.webp';
      candidate.decode().then(() => {
        if (request !== generation || assetFailed || destroyed) return;
        pendingFrame = false;
        index = next;
        image.src = candidate.src;
        image.dataset.frame = String(index);
        image.dataset.sequence = sequence;
      }).catch(() => {
        if (request === generation && !destroyed) image.dispatchEvent(new Event('error'));
      });
    }

    function tick(now) {
      if (!playing || destroyed) return;
      const next = Math.floor((now - clock) / 50) % sequences[state][1];
      if (next !== index) showFrame(next);
      frameRequest = requestAnimationFrame(tick);
    }

    function syncMotion() {
      if (frameRequest !== null) cancelAnimationFrame(frameRequest);
      frameRequest = null;
      playing = !destroyed && allowedMotion() && visible && !document.hidden &&
        !assetFailed && state !== 'unknown' && (!activityOnly || state === 'working');
      image.dataset.playing = String(playing);
      if (button) {
        button.hidden = false;
        button.disabled = assetFailed;
        button.textContent = allowedMotion() ? 'Pause' : 'Animer';
        button.setAttribute('aria-label', allowedMotion() ? 'Mettre Buddy en pause' : 'Animer Buddy');
      }
      if (playback) playback.textContent = assetFailed ? 'Animations indisponibles' :
        (!allowedMotion() ? 'Animation en pause' : (state === 'unknown' ? 'État non vérifié' : ''));
      if (playing) {
        clock = performance.now() - index * 50;
        frameRequest = requestAnimationFrame(tick);
      }
    }

    function observeState(observed) {
      if (destroyed) return;
      const next = Object.hasOwn(sequences, observed.state) ? observed.state : 'unknown';
      if (caption.textContent !== observed.caption) caption.textContent = observed.caption;
      if (state !== next) {
        state = next;
        cancelPending();
        index = 0;
        image.dataset.state = state;
        showFrame();
        syncMotion();
      }
      return observed;
    }

    function setMotion(value) {
      userMotion = value;
      if (!allowedMotion()) cancelPending();
      syncMotion();
      showFrame();
    }

    function setVisible(value) {
      visible = Boolean(value);
      if (!visible) cancelPending();
      syncMotion();
      showFrame();
    }

    const click = () => setMotion(!allowedMotion());
    const change = () => setMotion(null);
    const visibility = () => {
      if (document.hidden) cancelPending();
      syncMotion();
      if (!document.hidden) showFrame();
    };
    const error = () => {
      if (assetFailed || destroyed) return;
      assetFailed = true;
      image.src = '/buddy.png';
      image.alt = 'Logo STH ; animation Buddy indisponible';
      syncMotion();
    };

    button?.addEventListener('click', click);
    media.addEventListener('change', change);
    document.addEventListener('visibilitychange', visibility);
    image.addEventListener('error', error);
    image.dataset.state = state;
    showFrame();
    syncMotion();

    function destroy() {
      destroyed = true;
      cancelPending();
      syncMotion();
      button?.removeEventListener('click', click);
      media.removeEventListener('change', change);
      document.removeEventListener('visibilitychange', visibility);
      image.removeEventListener('error', error);
    }

    return Object.freeze({
      observe: run => observeState(root.FactoryBuddyState.observedState(run)),
      observeState,
      setMotion,
      setVisible,
      destroy
    });
  }

  root.FactoryBuddyPlayer = Object.freeze({create});
})(globalThis);
