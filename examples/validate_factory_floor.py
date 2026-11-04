"""Actual deterministic processes and real browser evidence; no model called."""
import argparse,json,os,shutil,sys,threading,time,subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from factory import Factory
from cockpit import make_server
parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=False)
runs=root/'runs';runs.mkdir();repo=root/'source';repo.mkdir()
def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.STDOUT)
git('init','-q');(repo/'README').write_text('Independent factory integration fixture. Deterministic processes, no LLM.\n');git('add','.');git('-c','user.name=Factory test','-c','user.email=factory@example.invalid','commit','-qm','fixture')
gates=[root/f'gate{i}' for i in range(4)];result={};checks={};errors=[]
code="""import json,sys,time
from pathlib import Path
request=json.load(sys.stdin)
identifier=request['task']['id']
number=int(identifier[-3:])
gates=GATES
gate=Path(gates[number-1] if number<=3 else gates[3])
print('real deterministic worker '+identifier,flush=True)
while not gate.exists():time.sleep(.02)
if number==2:raise SystemExit(7)
Path(identifier+'.txt').write_text('completed '+identifier)
""".replace('GATES',repr([str(g) for g in gates]))
policy={'commands':{'worker':[sys.executable,'-c',code]},'workers':3,'max_tasks':40,'task_timeout':150,'run_timeout':240}
plan={'tasks':[{'id':f'task{i:03}','runtime':'command','command':'worker',**({'depends_on':['task002']} if i==31 else {})} for i in range(1,32)]}
server=make_server(runs,port=0);threading.Thread(target=server.serve_forever,daemon=True).start()
def work():result.update(Factory(repo,runs/'atelier-31',policy).run(plan))
worker=threading.Thread(target=work,daemon=True)
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=shutil.which('chromium'),headless=True,args=['--no-sandbox'])
  context=browser.new_context(viewport={'width':1600,'height':1050},record_video_dir=str(root),record_video_size={'width':1600,'height':1050},reduced_motion='no-preference')
  page=context.new_page();video=page.video;page.on('pageerror',lambda e:errors.append(str(e)));page.goto(server.url)
  page.wait_for_timeout(600);assert page.locator('.station-buddy').count()==0;page.screenshot(path=str(root/'01-atelier-vide.png'));checks['zero_tasks_zero_buddies']=True
  worker.start();page.wait_for_timeout(700);page.locator('#refresh').click();page.get_by_role('button',name='atelier-31 · running',exact=True).click()
  page.wait_for_function("() => document.querySelector('[data-count=working] .count-value')?.textContent==='3'")
  page.locator('#atelier').scroll_into_view_if_needed();page.wait_for_timeout(700)
  assert page.locator('.station-buddy').count()==24
  page.wait_for_function("() => [...document.querySelectorAll('.station-buddy')].every(i=>i.complete && i.naturalWidth===384)")
  checks['all_waiting_and_working_buddies_loaded']=True
  assert page.locator('.station[data-state=working]').count()==3
  assert page.locator('.station[data-state=working] img[data-playing=true]').count()==3
  first=page.locator('.station[data-task=task001] img').get_attribute('data-frame');page.wait_for_timeout(300);assert page.locator('.station[data-task=task001] img').get_attribute('data-frame')!=first
  page.screenshot(path=str(root/'02-trois-buddies-au-travail.png'));checks['three_parallel_actual_workers']=True
  page.locator('#motion-toggle').click();held=page.locator('.station[data-task=task001] img').get_attribute('data-frame');page.wait_for_timeout(250);assert page.locator('.station[data-task=task001] img').get_attribute('data-frame')==held
  checks['pause_only_presentation']=True;page.locator('#motion-toggle').click()
  page.locator('#task-page-next').click();assert page.locator('.station-buddy').count()==7;assert page.locator('.station[data-task=task031]').count()==1
  page.locator('#task-page-prev').click();assert page.locator('.station-buddy').count()==24;checks['31_actual_tasks_paginated_max_24']=True
  page.locator('#task-state-filter').select_option('working');assert page.locator('.station-buddy').count()==3;page.locator('#task-state-filter').select_option('all')
  page.locator('#task-search').fill('task001');assert page.locator('.station-buddy').count()==1;page.get_by_role('button',name='Inspecter task001',exact=True).click();page.wait_for_function("() => document.querySelector('#details').textContent.includes('real deterministic worker task001')");page.locator('#task-search').fill('');checks['filter_search_selection_real_logs']=True
  page.evaluate("""() => {const original=window.fetch;window.__originalFetch=original;window.fetch=(url,options)=>String(url).includes('/api/review?run=atelier-31&task=task002')?new Promise((resolve,reject)=>setTimeout(()=>original(url,options).then(resolve,reject),900)):original(url,options);} """)
  page.get_by_role('button',name='Inspecter task002',exact=True).click()
  assert 'real deterministic worker task001' not in page.locator('#details').inner_text()
  page.get_by_role('button',name='Inspecter task003',exact=True).click()
  page.wait_for_function("() => document.querySelector('#details').textContent.includes('real deterministic worker task003')")
  page.wait_for_timeout(1100)
  assert 'real deterministic worker task002' not in page.locator('#details').inner_text()
  page.evaluate('() => {window.fetch=window.__originalFetch;}')
  checks['late_review_cannot_replace_selected_task_proofs']=True
  page.locator('#tasks').locator('.station').last.scroll_into_view_if_needed();page.wait_for_timeout(200)
  assert page.locator('.station[data-task=task001] img').get_attribute('data-playing')=='false'
  checks['offscreen_working_buddies_suspend_animation']=True
  page.locator('#atelier').scroll_into_view_if_needed()
  for gate in gates[:3]:gate.touch()
  page.wait_for_timeout(1200);page.locator('#refresh').click();page.wait_for_function("() => document.querySelector('[data-count=success] .count-value')?.textContent==='2' && document.querySelector('[data-count=error] .count-value')?.textContent==='2'")
  page.locator('#atelier').scroll_into_view_if_needed();page.wait_for_timeout(500);page.screenshot(path=str(root/'03-etats-mixtes.png'));checks['success_error_work_wait_same_real_run']=True
  page.emulate_media(reduced_motion='reduce');page.wait_for_timeout(200);assert page.locator('img.station-buddy[data-playing=true]').count()==0;checks['reduced_motion_all_workers_static']=True
  page.wait_for_function("() => [...document.querySelectorAll('.station-buddy')].every(i=>i.complete && i.naturalWidth===384)")
  page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(200);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.locator('.station').first.scroll_into_view_if_needed();page.screenshot(path=str(root/'04-atelier-mobile.png'))
  page.set_viewport_size({'width':320,'height':750});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');checks['mobile_320_390_no_overflow']=True
  page.set_viewport_size({'width':1600,'height':1050});page.emulate_media(reduced_motion='no-preference');gates[3].touch();worker.join(timeout=30);assert not worker.is_alive()
  page.locator('#refresh').click();page.wait_for_function("() => document.querySelector('[data-count=success] .count-value')?.textContent==='29'")
  assert page.locator('[data-count=error] .count-value').inner_text()=='2';assert page.locator('[data-count=working] .count-value').inner_text()=='0'
  assert page.locator('.station[data-task=task001]').get_attribute('data-state')=='success';assert page.locator('.station[data-task=task002]').get_attribute('data-state')=='error'
  assert page.locator('img.station-buddy[data-playing=true]').count()==0
  page.locator('#atelier').scroll_into_view_if_needed();page.wait_for_timeout(500);page.screenshot(path=str(root/'05-lot-termine.png'))
  checks['failed_run_keeps_29_successful_task_buddies']=True
  page.get_by_role('button',name='Inspecter task001',exact=True).focus();page.locator('#refresh').click();page.get_by_role('button',name='Inspecter task001',exact=True).focus();page.wait_for_timeout(3300);assert page.evaluate("document.activeElement.textContent==='Inspecter task001'");checks['polling_preserves_task_focus']=True
  assert not errors,errors;context.close();video.save_as(str(root/'factory-floor.webm'));Path(video.path()).unlink(missing_ok=True);browser.close()
 checks.update({'source_git_unchanged':git('status','--short').decode()=='','model_called':False,'run_status':result['status'],'browser_errors':errors})
 assert result['status']=='failed';(root/'checks.json').write_text(json.dumps(checks,indent=2));(root/'run-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(checks,indent=2))
finally:
 for gate in gates:gate.touch()
 if worker.ident:worker.join(timeout=10)
 server.shutdown();server.server_close()
