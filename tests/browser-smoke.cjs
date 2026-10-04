// Real browser checks using Windows Edge and Node's built-in CDP WebSocket.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const root = path.resolve(__dirname, '..');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'botmanager-ui-'));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let server, browser, ws;
async function until(check) {
  const deadline = Date.now()+15000;
  while(Date.now()<deadline) { const result=await check(); if(result)return result; await delay(100); }
  throw new Error('Browser check timed out');
}
async function main() {
  const python = String.raw`import json,sys
from botmanager.manager import Manager
from botmanager.server import Portal
m=Manager(sys.argv[1])
bot_id=m.save_bot({'name':'Smoke bot','mode':'demo','prefix':'!'})
s=Portal(('127.0.0.1',0),m,'smoke-password')
print(json.dumps({'port':s.server_address[1],'id':bot_id}),flush=True)
s.serve_forever()`;
  server=spawn(path.join(root,'.venv/Scripts/python.exe'),['-c',python,path.join(temporary,'data')],{cwd:root,windowsHide:true});
  let output='';server.stdout.on('data',chunk=>output+=chunk);server.stderr.on('data',chunk=>process.stderr.write(chunk));
  await until(()=>output.includes('\n'));
  console.log('UI fixture ready.');
  const fixture=JSON.parse(output.trim().split('\n')[0]), base=`http://127.0.0.1:${fixture.port}`, botPath=`/bots/${fixture.id}`;
  const profile=path.join(temporary,'edge');
  browser=spawn(String.raw`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`,['--headless=new','--disable-gpu','--disable-extensions','--no-first-run','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
  const portFile=path.join(profile,'DevToolsActivePort');
  await until(()=>fs.existsSync(portFile));
  const debugPort=fs.readFileSync(portFile,'utf8').split('\n')[0];
  const target=await (await fetch(`http://127.0.0.1:${debugPort}/json/new?${encodeURIComponent(base+botPath+'/settings')}`,{method:'PUT'})).json();
  ws=new WebSocket(target.webSocketDebuggerUrl);await Promise.race([once(ws,'open'),delay(10000).then(()=>{throw new Error('DevTools connection timed out');})]);
  console.log('Headless browser connected.');
  let nextId=0;const pending=new Map(), errors=[];
  ws.addEventListener('message',event=>{const result=JSON.parse(event.data);if(result.id){const p=pending.get(result.id);pending.delete(result.id);result.error?p.reject(new Error(result.error.message)):p.resolve(result.result);}else if(result.method==='Runtime.exceptionThrown')errors.push(result.params.exceptionDetails);});
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++nextId,timer=setTimeout(()=>{pending.delete(id);reject(new Error(`DevTools timed out: ${method}`));},10000);pending.set(id,{resolve:value=>{clearTimeout(timer);resolve(value);},reject:error=>{clearTimeout(timer);reject(error);}});ws.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw new Error(r.exceptionDetails.text+': '+r.exceptionDetails.exception?.description);return r.result.value;};
  await send('Runtime.enable');
  await until(()=>evaluate(`document.readyState==='complete' && typeof navigate==='function'`));
  await evaluate(`$('#login-form').elements.password.value='smoke-password';$('#login-form').requestSubmit();`);
  await until(()=>evaluate(`!$('#shell').hidden && !$('#bot-settings-view').hidden`));
  assert.equal(await evaluate(`$('#page-title').textContent`),'Smoke bot');
  assert.equal(await evaluate(`$('#bot-page-form').elements.name.value='Draft name';$('#bot-page-form').dispatchEvent(new Event('input',{bubbles:true}));refresh().then(()=>$('#bot-page-form').elements.name.value)`),'Draft name');
  await evaluate(`$('#bot-page-form').requestSubmit()`);
  await until(()=>evaluate(`!busy && state.bots[0].name==='Draft name'`));
  await evaluate(`navigate('/')`);
  assert.equal(await evaluate(`document.querySelectorAll('[data-card]').length`),1);
  await evaluate(`$('#fleet-search').value='missing';$('#fleet-search').dispatchEvent(new Event('input'));`);
  assert.equal(await evaluate(`document.querySelector('[data-card]').hidden`),true);
  assert.equal(await evaluate(`!!$('#fleet-no-results')`),true);
  await evaluate(`$('#reset-fleet-filter').click()`);
  assert.equal(await evaluate(`document.querySelector('[data-card]').hidden`),false);
  await evaluate(`document.querySelector('[data-action="delete"]').click()`);
  await until(()=>evaluate(`$('#confirm-dialog').open`));
  assert.equal(await evaluate(`document.activeElement.id`),'confirm-cancel');
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  await until(()=>evaluate(`!$('#confirm-dialog').open`));
  assert.equal(await evaluate(`state.bots.length`),1);
  await evaluate(`navigate('/bots/new')`);
  assert.equal(await evaluate(`$('#bot-dialog').open`),true);
  await evaluate(`toast('Modal validation message',true)`);
  assert.equal(await evaluate(`$('#notifications').matches(':popover-open')`),true);
  assert.equal(await evaluate(`!!document.querySelector('.notification.error')`),true);
  await evaluate(`document.querySelectorAll('.notification .close').forEach(b=>b.click());$('#bot-dialog [data-close]').click()`);
  await until(()=>evaluate(`location.pathname==='/' && !document.body.classList.contains('modal-open')`));
  for(const width of [390,768,1440]) {
    await send('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});
    assert.equal(await evaluate(`document.documentElement.scrollWidth<=innerWidth`),true,`Fleet overflow at ${width}px`);
  }
  if(process.env.BOTMANAGER_SCREENSHOT) {
    const shot=await send('Page.captureScreenshot',{format:'png'});
    fs.writeFileSync(process.env.BOTMANAGER_SCREENSHOT,Buffer.from(shot.data,'base64'));
  }

  await evaluate(`document.querySelector('[data-card]').click()`);
  assert.equal(await evaluate(`location.pathname`),botPath);
  await evaluate(`history.back()`);await until(()=>evaluate(`location.pathname==='/' && route.view==='overview'`));
  await evaluate(`history.forward()`);await until(()=>evaluate(`location.pathname==='${botPath}' && route.view==='bot'`));
  await evaluate(`document.querySelector('#bot-tabs a[href$="/cogs"]').click()`);
  assert.equal(await evaluate(`location.pathname`),botPath+'/cogs');
  await evaluate(`document.querySelector('[data-module="cogs.general"][data-cog-action="settings"]').click()`);
  await until(()=>evaluate(`!$('#cog-page-form button').disabled`));
  assert.equal(await evaluate(`location.pathname`),botPath+'/cogs/cogs.general/settings');
  await evaluate(`$('#cog-page-form').elements.settings.value=JSON.stringify({greeting:'Browser smoke'});$('#cog-page-form').requestSubmit()`);
  await until(()=>evaluate(`!busy`));
  assert.equal(await evaluate(`api('/api/bots/${fixture.id}/settings/cogs.general').then(x=>x.settings.greeting)`),'Browser smoke');
  await evaluate(`document.querySelector('#bot-tabs a[href$="/console"]').click()`);
  await send('Page.reload');
  await until(()=>evaluate(`document.readyState==='complete' && typeof route!=='undefined' && !$('#shell').hidden && view==='logs'`));
  assert.equal(await evaluate(`location.pathname`),botPath+'/console');
  assert.equal(await evaluate(`$('#log-bot').hidden`),true);
  await evaluate(`$('#log-follow').click()`);
  assert.equal(await evaluate(`followLogs`),false);
  await evaluate(`$('#log-follow').click()`);
  assert.equal(await evaluate(`followLogs`),true);
  assert.equal(await evaluate(`document.querySelectorAll('#bot-tabs a').length`),4);
  await evaluate(`$('#admin-nav').click()`);
  await until(()=>evaluate(`typeof adminData!=='undefined' && adminData && document.querySelectorAll('.account-card').length===1`));
  await evaluate(`api('/api/accounts',{username:'disposable',password:'disposable-password',role:'member'}).then(loadAccounts)`);
  await evaluate(`document.querySelector('[data-delete-account="'+adminData.accounts.find(a=>a.username==='disposable').id+'"]').click()`);
  await until(()=>evaluate(`$('#confirm-dialog').open`));
  await evaluate(`$('#confirm-accept').click()`);
  await until(()=>evaluate(`!adminData.accounts.some(a=>a.username==='disposable')`));
  await evaluate(`$('#new-account').click();const f=$('#account-form');f.elements.username.value='reader';f.elements.password.value='reader-smoke-password';f.querySelector('[data-override]').checked=true;f.querySelector('[data-scope="${fixture.id}"][value="view"]').checked=true;f.querySelector('[data-scope="${fixture.id}"][value="logs"]').checked=true;f.dispatchEvent(new Event('change',{bubbles:true}));f.requestSubmit()`);
  await until(()=>evaluate(`!$('#account-dialog').open && document.querySelectorAll('.account-card').length===2`));
  await evaluate(`$('#logout').click()`);await until(()=>evaluate(`$('#shell').hidden`));
  await evaluate(`$('#login-form').elements.username.value='reader';$('#login-form').elements.password.value='reader-smoke-password';$('#login-form').requestSubmit()`);
  await until(()=>evaluate(`!$('#shell').hidden && currentUser?.username==='reader'`));
  assert.equal(await evaluate(`$('#admin-nav').hidden`),true);
  assert.equal(await evaluate(`$('#forbidden-view').hidden`),false);
  await evaluate(`navigate('${botPath}')`);
  assert.equal(await evaluate(`$('#bot-summary [data-action="start"]').disabled`),true);
  assert.equal(await evaluate(`fetch('/api/bots/${fixture.id}/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(r=>r.status)`),403);
  assert.equal(await evaluate(`fetch('/api/accounts').then(r=>r.status)`),403);
  await evaluate(`navigate('${botPath}/settings')`);
  assert.equal(await evaluate(`$('#forbidden-view').hidden`),false);
  // Disable page scripts and force a native form submission. It must remain POST.
  await send('Emulation.setScriptExecutionDisabled',{value:true});
  await send('Page.reload');
  await until(()=>evaluate(`document.readyState==='complete' && !!document.querySelector('#login-form')`));
  assert.equal(await evaluate(`document.querySelector('#login-form').method`),'post');
  await evaluate(`document.querySelector('[name="password"]').value='never-send-in-url';document.querySelector('#login-form').submit()`);
  await until(()=>evaluate(`location.pathname==='/api/login' && document.readyState==='complete'`));
  assert.equal(await evaluate(`location.search`),'');
  assert.equal(await evaluate(`document.body.textContent.includes('never-send-in-url')`),false);
  assert.deepEqual(errors,[]);
  console.log('Browser checks passed: filters, responsive layouts, modals, notifications, console controls, navigation, settings, accounts, scoped permissions, and safe login.');
  await send('Browser.close');
}
main().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{
  if(ws)ws.close();
  for(const child of [browser,server])if(child&&child.exitCode===null){child.kill();await Promise.race([once(child,'exit'),delay(3000)]);}
  // Only remove the unique temporary directory created by this test.
  if(path.dirname(path.resolve(temporary))===path.resolve(os.tmpdir())&&path.basename(temporary).startsWith('botmanager-ui-')) {
    try{fs.rmSync(temporary,{recursive:true,force:true,maxRetries:3,retryDelay:200});}catch{}
  }
});
