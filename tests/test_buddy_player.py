from pathlib import Path
import shutil
import subprocess
import unittest


HARNESS = r'''
const assert = require('node:assert/strict');

class Element extends EventTarget {
  constructor() {
    super();
    this.dataset = {};
    this.attributes = {};
    this.textContent = '';
    this.src = '';
    this.listeners = new Map();
  }
  addEventListener(type, listener) {
    super.addEventListener(type, listener);
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(listener);
  }
  removeEventListener(type, listener) {
    super.removeEventListener(type, listener);
    this.listeners.get(type)?.delete(listener);
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  listenerCount() {
    return [...this.listeners.values()].reduce((total, entries) => total + entries.size, 0);
  }
}

const media = new Element();
media.matches = false;
globalThis.matchMedia = () => media;
globalThis.document = new Element();
document.hidden = false;
const frames = new Map();
let frameID = 0;
globalThis.requestAnimationFrame = callback => {
  const identifier = ++frameID;
  frames.set(identifier, callback);
  return identifier;
};
globalThis.cancelAnimationFrame = identifier => frames.delete(identifier);

const decodes = [];
globalThis.Image = class {
  decode() {
    return new Promise((resolve, reject) => {
      decodes.push({image: this, resolve, reject, settled: false});
    });
  }
};
async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}
async function finishDecodes() {
  for (const item of decodes) {
    if (!item.settled) {
      item.settled = true;
      item.resolve();
    }
  }
  await flushPromises();
}
function fixture(options = {}) {
  const image = new Element(), caption = new Element();
  const button = new Element(), playback = new Element();
  const player = FactoryBuddyPlayer.create({image, caption, button, playback, ...options});
  return {image, caption, button, playback, player};
}
require(process.argv[1]);
'''


@unittest.skipUnless(shutil.which('node'), 'Node required for Buddy player lifecycle tests')
class BuddyPlayerTests(unittest.TestCase):
    def run_player(self, scenario):
        module = Path(__file__).resolve().parents[1] / 'web/buddy-player.js'
        script = HARNESS + '\n(async () => {\n' + scenario + r'''
        })().catch(error => { console.error(error); process.exitCode = 1; });
        '''
        result = subprocess.run([shutil.which('node'), '-e', script, str(module)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_initial_waiting_pose_survives_visibility_and_motion_setup(self):
        self.run_player(r'''
for (const reducedMotion of [false, true]) {
  media.matches = reducedMotion;
  const {image, caption, player} = fixture({activityOnly: true});
  player.setVisible(false);
  player.setMotion(null);
  player.observeState({state: 'waiting', caption: 'Tâche en attente'});
  player.setVisible(true);
  await finishDecodes();
  assert.match(image.src, /\/ok\/0000\.webp$/);
  assert.equal(image.dataset.state, 'waiting');
  assert.equal(image.dataset.playing, 'false');
  assert.equal(caption.textContent, 'Tâche en attente');
  assert.equal(frames.size, 0);
  player.destroy();
}
''')

    def test_returning_to_visible_tab_retries_cancelled_static_pose(self):
        self.run_player(r'''
for (const state of ['waiting', 'success', 'error']) {
  const {image, caption, player} = fixture({activityOnly: true});
  player.observeState({state, caption: 'Observed ' + state});
  document.hidden = true;
  document.dispatchEvent(new Event('visibilitychange'));
  await finishDecodes();
  assert.equal(image.src, '', 'a decode cancelled on hide must not paint');
  document.hidden = false;
  document.dispatchEvent(new Event('visibilitychange'));
  await finishDecodes();
  const sequence = {waiting: 'ok', success: 'done', error: 'error'}[state];
  assert.ok(image.src.endsWith('/' + sequence + '/0000.webp'));
  assert.equal(caption.textContent, 'Observed ' + state);
  assert.equal(image.dataset.playing, 'false');
  assert.equal(frames.size, 0);
  player.destroy();
}
''')

    def test_destroy_stops_animation_discards_pending_decode_and_removes_listeners(self):
        self.run_player(r'''
const {image, button, player} = fixture();
assert.equal(image.dataset.playing, 'true');
assert.ok(frames.size > 0);
for (const target of [image, button, media, document]) assert.ok(target.listenerCount() > 0);
const queuedCallbacks = [...frames.values()];
player.destroy();
assert.equal(image.dataset.playing, 'false');
assert.equal(frames.size, 0);
for (const target of [image, button, media, document]) assert.equal(target.listenerCount(), 0);
await finishDecodes();
assert.equal(image.src, '', 'a late decode must not repaint a destroyed station');
for (const callback of queuedCallbacks) callback(performance.now() + 1000);
button.dispatchEvent(new Event('click'));
media.dispatchEvent(new Event('change'));
document.dispatchEvent(new Event('visibilitychange'));
image.dispatchEvent(new Event('error'));
assert.equal(frames.size, 0);
assert.equal(image.src, '');
''')

    def test_pausing_keeps_observed_state_changes_and_rejects_stale_decode(self):
        self.run_player(r'''
const {image, caption, player} = fixture({activityOnly: true});
await finishDecodes();
player.observeState({state: 'working', caption: 'Tâche en cours'});
assert.equal(image.dataset.playing, 'true');
player.setMotion(false);
assert.equal(image.dataset.playing, 'false');
assert.equal(frames.size, 0);
player.observeState({state: 'success', caption: 'Tâche terminée avec succès'});
assert.equal(caption.textContent, 'Tâche terminée avec succès');
const currentPose = decodes.at(-1);
currentPose.settled = true;
currentPose.resolve();
await flushPromises();
assert.match(image.src, /\/done\/0000\.webp$/);
await finishDecodes();
assert.match(image.src, /\/done\/0000\.webp$/, 'older work decodes must not overwrite the newer success pose');
assert.equal(image.dataset.state, 'success');
assert.equal(image.dataset.playing, 'false');
player.observeState({state: 'error', caption: 'Tâche en échec'});
await finishDecodes();
assert.match(image.src, /\/error\/0000\.webp$/);
assert.equal(caption.textContent, 'Tâche en échec');
assert.equal(image.dataset.playing, 'false');
assert.equal(frames.size, 0);
player.destroy();
''')


if __name__ == '__main__':
    unittest.main()
