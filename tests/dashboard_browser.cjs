// Optional UI regression: AM_PLAYWRIGHT_MODULE=/path/to/playwright node tests/dashboard_browser.cjs
const {chromium}=require(process.env.AM_PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const {execFileSync}=require('node:child_process');
const repo=path.resolve(__dirname,'..');
const artifacts=process.env.AM_UI_ARTIFACT_DIR||fs.mkdtempSync(path.join(os.tmpdir(),'am-ui-'));
fs.mkdirSync(artifacts,{recursive:true});
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const html=execFileSync(process.env.PYTHON||'python3',['-c',"import runpy; print(runpy.run_path('bin/am')['dashboard_html']({'project':'UI fixture'}))"],{cwd:repo,encoding:'utf8'});
const now=Date.now()/1000;
const sid='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', native='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const logical='codex-'+crypto.createHash('sha256').update(native).digest('hex').slice(0,32);
const sessions=[{short:'aaaaaaaa',agent:'claude-code',quiet:1,title:'回放核验主会话',progress:'保留原有会话功能',delegate_session_ids:[sid]},
 {short:'bbbbbbbb',agent:'codex',quiet:2,title:'Codex 主会话',delegate_session_ids:[native,logical]}];
const common={effort:'high',created_at:now-120,elapsed_seconds:120,heartbeat_age_seconds:2,progress_age_seconds:4,
 review:'pending',collected_at:null,conversation:'unknown',has_thread:true,phase:'executing',warnings:[],worker_alive:true,backend_alive:true,
 observed_tokens:24500,cached_tokens:22000,active_commands:1,parent_host:'claude-code'};
let jobs=[{...common,id:'j_live',task_id:'t',session_id:sid,label:'核对回放与冻结样本',work_item:'replay-check',agent:'codex-reviewer',provider_name:'codex',model:'gpt-6-astra',status:'running',waiting:true},
 {...common,id:'j_failed',task_id:'t2',session_id:'unmatched-parent',label:'工作区准备失败',agent:'codex-builder',provider_name:'codex',model:'gpt-6.1-sol',status:'failed',waiting:false,error:'<img src=x onerror="window.pwned=1"> timeout',failure_kind:'infrastructure'},
 {...common,id:'j_complete',task_id:'t',session_id:sid,label:'整理研究结果',agent:'deepseek-docs',provider_name:'deepseek-company',model:'deepseek',status:'completed',waiting:false,review:'accepted',collected_at:now,conversation:'archived'},
 {...common,id:'j_native',task_id:'t3',session_id:logical,label:'原生宿主子任务',agent:'claude-explorer',provider_name:'claude',model:'sonnet',status:'cancelled',waiting:false}];
const overview=()=>({jobs:JSON.parse(JSON.stringify(jobs)),sampled_at:Date.now()/1000,errors:0,source:'/fixture/delegate',coverage:'活动索引 + 有界历史；只读'});
const state={project:'fixture',store:'/fixture/.agents',generated:new Date().toISOString(),tasks:[],sessions,hidden:[],active:['aaaaaaaa'],counts:{active:1,tasks_open:0,sessions:2},window_days:30,delegate_overview:overview()};
(async()=>{
 const b=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{
 const page=await b.newPage({viewport:{width:1440,height:1080},timezoneId:'Asia/Shanghai'});
 const errors=[];let posts=0,delegateReads=0;
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://am.fixture/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(route.request().method()!=='GET'){posts++;return route.fulfill({status:405,body:'read-only fixture'});}
  if(path==='/')return route.fulfill({contentType:'text/html',body:html});
  if(path==='/api/state'){await new Promise(r=>setTimeout(r,3000));return route.fulfill({contentType:'application/json',body:JSON.stringify(state)});}
  if(path==='/api/delegate'){delegateReads++;return route.fulfill({contentType:'application/json',body:JSON.stringify(overview())});}
  return route.fulfill({status:404,body:''});
 });
 const start=Date.now();
 await page.goto('http://am.fixture/#delegate',{waitUntil:'domcontentloaded'});
 await page.waitForSelector('[data-job-card="j_live"]',{timeout:2000});
 const firstTaskMs=Date.now()-start;
 assert(firstTaskMs<2500,'live tasks must render before slow session snapshot');
 await page.waitForFunction(()=>document.querySelector('[data-short="aaaaaaaa"]'));
 await page.screenshot({path:path.join(artifacts,'delegate-desktop.png')});
 await page.locator('.item[data-short=""]').click();
 assert.equal(await page.locator('h1').innerText(),'工作区概览');
 await page.locator('.delegate-entry').click();
 assert.equal(await page.locator('h1').innerText(),'子任务工作台');
 await page.locator('[data-job-filter="active"]').click();
 assert.equal(await page.locator('[data-job-card]').count(),1);
 assert((await page.locator('[data-job-card="j_live"]').textContent()).includes('等待计算'));
 await page.selectOption('#delegate-provider','deepseek-company');
 assert.equal(await page.locator('[data-job-card]').count(),0);
 await page.selectOption('#delegate-provider','');
 await page.locator('[data-job-filter="all"]').click();
 await page.locator('#q').fill('astra');
 assert.equal(await page.locator('[data-job-card]').count(),1);
 await page.locator('#q').fill('');
 await page.locator('[data-job-card="j_live"] [data-jump]').click();
 assert.equal(await page.locator('h1').innerText(),'回放核验主会话');
 assert.equal(await page.locator('[data-job-card]').count(),2);
 await page.locator('.delegate-entry').click();
 await page.locator('[data-job-card="j_native"] [data-jump]').click();
 assert.equal(await page.locator('h1').innerText(),'Codex 主会话');
 assert.equal(await page.locator('[data-job-card]').count(),1);
 await page.locator('.delegate-entry').click();
 await page.locator('details[data-job="j_live"] summary').click();
 jobs[0]={...jobs[0],status:'completed',waiting:false,finished_at:now+5,heartbeat_age_seconds:6};
 await page.waitForFunction(()=>document.querySelector('[data-job-card="j_live"] .job-top').textContent.includes('执行完成'),null,{timeout:6000});
 assert.equal(await page.locator('details[data-job="j_live"]').evaluate(e=>e.open),true);
 assert.equal(await page.evaluate(()=>window.pwned),undefined);
 assert.equal(await page.locator('[data-job-card="j_failed"] img').count(),0);
 await page.locator('#pause').click();
 await page.waitForTimeout(150);const pausedReads=delegateReads;
 await page.waitForTimeout(2800);assert.equal(delegateReads,pausedReads);
 await page.locator('#pause').click();
 await page.setViewportSize({width:390,height:844});
 await page.waitForTimeout(200);
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:path.join(artifacts,'delegate-mobile.png'),fullPage:true});
 assert.equal(posts,0);assert.deepEqual(errors,[]);
 const report={ok:true,artifacts,firstTaskMs,delegateReads,mutations:posts,errors,checks:['slow-session-independent-first-paint','clickable-sidebar','status-filter','provider-filter','search','exact-parent-jump','native-host-parent-jump','delegate-only-live-update','expanded-details-preserved','escaped-output','pause-resume','mobile-no-overflow']};
 fs.writeFileSync(path.join(artifacts,'ui-acceptance.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify(report));
 }finally{await b.close();}
})().catch(e=>{console.error(e.stack);process.exit(1)});
