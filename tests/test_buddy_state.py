from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node required for the optional Buddy UI state mapping tests')
class BuddyStateTests(unittest.TestCase):
    def test_reactions_follow_only_observed_states(self):
        module = Path(__file__).resolve().parents[1] / 'web/buddy-state.js'
        script = '''
const assert = require('node:assert/strict');
const {observedState} = require(process.argv[1]);
assert.equal(observedState(null).state, 'waiting');
assert.equal(observedState({status:'not_started'}).state, 'waiting');
assert.equal(observedState({status:'running',tasks:{a:{status:'running'}}}).state, 'working');
assert.equal(observedState({status:'running',tasks:{a:{status:'succeeded'}}}).state, 'working');
assert.equal(observedState({status:'succeeded',tasks:{a:{status:'succeeded'}}}).state, 'success');
assert.equal(observedState({status:'succeeded',tasks:{a:{status:'running'}}}).state, 'unknown');
for (const status of ['failed','timed_out','cancelled','interrupted','blocked']) {
  assert.equal(observedState({status}).state, 'error');
}
assert.equal(observedState({status:'unrecognised'}).state, 'unknown');
assert.equal(observedState({status:'running',progress:99}).progress, null);
assert.ok(Object.isFrozen(observedState({status:'running'})));
console.log('Observed waiting/work/success/error transitions passed; no invented progress.');
'''
        result = subprocess.run([shutil.which('node'), '-e', script, str(module)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
