"""Execute the browser's provider-neutral projection in Node, without a DOM."""
import shutil
import subprocess
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node is required for browser model tests')
class FactoryViewTests(unittest.TestCase):
    def check_js(self, source):
        code = "const assert = require('node:assert/strict'); const view = require('./web/factory-view.js');\n" + source
        result = subprocess.run(['node', '-e', code], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_zero_and_browser_export(self):
        self.check_js("""
const empty = view.project(null);
assert.deepEqual(empty.tasks, []); assert.deepEqual(empty.visible, []);
assert.deepEqual(empty.counts, {total:0, waiting:0, working:0, success:0, error:0, unknown:0});
assert.equal(empty.page, 0); assert.equal(empty.pageCount, 0); assert.equal(empty.pageSize, 24);
const fs=require('node:fs'),vm=require('node:vm'), context={};
vm.runInNewContext(fs.readFileSync('./web/factory-view.js','utf8'),context);
assert.equal(typeof context.FactoryView.project,'function');
""")

    def test_parallel_own_states_and_plan_order(self):
        self.check_js("""
const result=view.project({status:'running',supervisor_active:true,
 plan:{tasks:[{id:'build'},{id:'test',depends_on:['build']},{id:'wait'}]},
 tasks:{test:{status:'running'},build:{status:'succeeded'},wait:{status:'pending'},extra:{status:'failed'}}});
assert.deepEqual(result.tasks.map(t=>t.id),['build','test','wait','extra']);
assert.deepEqual(result.tasks.map(t=>t.state),['success','working','waiting','error']);
assert.deepEqual(result.tasks.map(t=>t.index),[0,1,2,3]);
assert.deepEqual(result.tasks[1].depends_on,['build']);
assert.deepEqual(result.counts,{total:4,waiting:1,working:1,success:1,error:1,unknown:0});
""")

    def test_success_remains_success_in_failed_run(self):
        self.check_js("""
const result=view.project({status:'failed',tasks:{done:{status:'succeeded'},bad:{status:'failed'},idle:{status:'not_started'}}});
assert.deepEqual(result.tasks.map(t=>t.state),['success','error','waiting']);
""")

    def test_running_requires_verified_activity(self):
        self.check_js("""
for(const supervisor_active of [false,null,undefined,1,'true']) {
 const r=view.project({status:'running',supervisor_active,tasks:{a:{status:'running'}}});
 assert.equal(r.tasks[0].state,'unknown');
}
assert.equal(view.project({status:'failed',supervisor_active:true,tasks:{a:{status:'running'}}}).tasks[0].state,'unknown');
assert.equal(view.project({status:'interrupted',tasks:{a:{status:'interrupted'}}}).tasks[0].state,'error');
""")

    def test_thousand_tasks_bounded_paging(self):
        self.check_js("""
const snapshot={plan:{tasks:Array.from({length:1000},(_,i)=>({id:'task_'+i}))}};
let r=view.project(snapshot,{pageSize:999,page:999});
assert.equal(r.tasks.length,1000); assert.equal(r.pageSize,24); assert.equal(r.pageCount,42);
assert.equal(r.page,41); assert.equal(r.visible.length,16); assert.equal(r.visible[0].id,'task_984');
assert.equal(r.counts.waiting,1000);
r=view.project(snapshot,{page:-5,pageSize:3}); assert.equal(r.page,0); assert.equal(r.visible.length,3);
""")

    def test_search_filter_clamping_counts(self):
        self.check_js("""
const snapshot={tasks:{alpha:{status:'failed'},beta:{status:'succeeded'},alphabet:{status:'cancelled'}}};
let r=view.project(snapshot,{query:' ALPHA ',filter:'error',page:100,pageSize:1});
assert.equal(r.filteredCount,2); assert.equal(r.page,1); assert.equal(r.visible[0].id,'alphabet');
assert.equal(r.counts.total,3); assert.equal(r.counts.success,1);
r=view.project(snapshot,{query:'no_match',filter:'unknown'}); assert.equal(r.filteredCount,0); assert.equal(r.pageCount,0); assert.equal(r.page,0);
r=view.project(snapshot,{filter:'<script>',pageSize:NaN,page:Infinity}); assert.equal(r.filteredCount,3); assert.equal(r.pageSize,24); assert.equal(r.page,0);
""")

    def test_duplicates_untrusted_values_dependencies(self):
        self.check_js("""
const snapshot=JSON.parse('{"status":"running","supervisor_active":true,"plan":{"tasks":[{"id":"a","depends_on":["b","b","../evil",null,42]},{"id":"a"},{"id":"<script>"},{"id":"b"}]},"tasks":{"a":{"status":"<img onerror=evil()>"},"b":{"status":"blocked"},"../escape":{"status":"succeeded"},"constructor":{"status":"succeeded"},"c":null}}');
const r=view.project(snapshot);
assert.deepEqual(r.tasks.map(t=>t.id),['a','b','constructor','c']);
assert.deepEqual(r.tasks[0].depends_on,['b']); assert.equal(r.tasks[0].state,'unknown');
assert.equal(r.tasks[0].status,'unknown'); assert.equal(r.tasks[1].state,'error');
assert.equal(r.tasks[2].state,'success'); assert.equal(r.tasks[3].state,'unknown');
assert.ok(r.tasks.every(t=>!t.caption.includes('<')));
""")

    def test_no_input_mutation_and_malformed_options(self):
        self.check_js("""
const input={status:'running',supervisor_active:true,plan:{tasks:[{id:'a',depends_on:['b']}]},tasks:{a:{status:'running'}}};
const before=JSON.stringify(input);
Object.freeze(input.plan.tasks[0].depends_on);Object.freeze(input.plan.tasks[0]);Object.freeze(input.plan.tasks);Object.freeze(input.plan);Object.freeze(input.tasks.a);Object.freeze(input.tasks);Object.freeze(input);
const result=view.project(input,null); assert.equal(JSON.stringify(input),before);
result.tasks[0].depends_on.push('c'); assert.deepEqual(input.plan.tasks[0].depends_on,['b']);
for(const malformed of [[],42,'oops',false]) assert.equal(view.project(malformed).tasks.length,0);
""")


if __name__ == '__main__':
    unittest.main()
