/* Shared by the browser and the route regression tests. */
(function (root) {
  function parseRoute(pathname) {
    const path = pathname.replace(/\/+$/, '') || '/';
    const globals = {'/':'overview','/admin':'admin','/cogs':'cogs','/logs':'logs','/bots/new':'create','/bots/import':'import','/cogs/new':'upload'};
    if (globals[path]) return {view:globals[path],botId:null};
    const match = path.match(/^\/bots\/([a-f0-9]{12})(?:\/(console|cogs|settings)(?:\/([^/]+)\/settings)?)?$/);
    if (!match || (match[3] && match[2] !== 'cogs')) return {view:'notfound',botId:null};
    let module;
    try { module = match[3] ? decodeURIComponent(match[3]) : null; } catch { return {view:'notfound',botId:null}; }
    return {botId:match[1],view:module?'cogsettings':(match[2]==='console'?'logs':match[2]||'bot'),module};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {parseRoute};
  else root.PortalRoutes = {parseRoute};
})(globalThis);

const $ = s => document.querySelector(s);
if(location.search){const url=new URL(location.href);for(const key of [...url.searchParams.keys()])if(key.toLowerCase()==='password')url.searchParams.delete(key);history.replaceState(null,'',url.pathname+url.search+url.hash);}
let currentUser=null, sessionEpoch=0, stateRequestVersion=0;
const canSite=p=>currentUser?.role==='admin'||currentUser?.site_permissions?.includes(p);
const canBot=(bot,p)=>currentUser?.role==='admin'||bot?.permissions?.includes(p);
let state = {bots: [], cogs: []}, view = 'overview', busy = false, refreshing = false, settingTarget = null;
let route = PortalRoutes.parseRoute(location.pathname), pageSettingsBotId = null, pageSettingsDirty = false, jsonTarget = null, jsonLoadVersion = 0, logLoadVersion = 0;
const escapeHTML = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(message, error=false) {
  const host=$('#notifications'), item=document.createElement('div');
  item.className=`notification ${error?'error':'success'}`;item.setAttribute('role',error?'alert':'status');
  const icon=document.createElement('span');icon.className='notification-icon';icon.textContent=error?'!':'✓';icon.setAttribute('aria-hidden','true');
  const copy=document.createElement('div'),title=document.createElement('strong'),text=document.createElement('p');
  title.textContent=error?'Something needs attention':'Update';text.textContent=message;copy.append(title,text);
  const close=document.createElement('button');close.type='button';close.className='close';close.setAttribute('aria-label','Dismiss notification');close.textContent='×';
  item.append(icon,copy,close);host.append(item);if(host.showPopover&&!host.matches(':popover-open'))host.showPopover();
  let timer;const remove=()=>{clearTimeout(timer);item.remove();if(!host.children.length&&host.hidePopover)host.hidePopover();};const schedule=()=>timer=setTimeout(remove,error?10000:6000);
  close.addEventListener('click',remove);item.addEventListener('pointerenter',()=>clearTimeout(timer));item.addEventListener('pointerleave',schedule);
  item.addEventListener('focusin',()=>clearTimeout(timer));item.addEventListener('focusout',schedule);schedule();
  while(host.children.length>4)host.firstElementChild.remove();
}
let confirmResolve=null;
function confirmAction(title,message,label='Delete') {
  if(confirmResolve)return Promise.resolve(false);
  const dialog=$('#confirm-dialog');$('#confirm-title').textContent=title;$('#confirm-message').textContent=message;$('#confirm-accept').textContent=label;
  return new Promise(resolve=>{confirmResolve=resolve;dialog.returnValue='';dialog.showModal();$('#confirm-cancel').focus();});
}
$('#confirm-accept').addEventListener('click',()=>$('#confirm-dialog').close('accept'));
$('#confirm-cancel').addEventListener('click',()=>$('#confirm-dialog').close());
$('#confirm-dialog').addEventListener('close',()=>{const resolve=confirmResolve;confirmResolve=null;resolve?.($('#confirm-dialog').returnValue==='accept');});
let followLogs=true;
function filterFleet() {
  const query=$('#fleet-search').value.trim().toLowerCase(),status=$('#fleet-status').value;
  let count=0;document.querySelectorAll('#fleet [data-card]').forEach(card=>{const bot=state.bots.find(b=>b.id===card.dataset.card);const visible=(!query||`${bot.name} ${bot.mode} ${bot.prefix}`.toLowerCase().includes(query))&&(status==='all'||bot.status===status);card.hidden=!visible;if(visible)count++;});
  $('#fleet-count').textContent=`${count} of ${state.bots.length} bots`;
  $('#fleet-no-results')?.remove();if(!count&&state.bots.length)$('#fleet').insertAdjacentHTML('beforeend','<div id="fleet-no-results" class="empty"><h2>No matching bots</h2><p>Try another name or change the status filter.</p><button type="button" id="reset-fleet-filter" class="secondary">Clear filters</button></div>');
}
$('#fleet-search').addEventListener('input',filterFleet);$('#fleet-status').addEventListener('change',filterFleet);
$('#log-follow').addEventListener('click',()=>{followLogs=!followLogs;$('#log-follow').setAttribute('aria-pressed',String(followLogs));$('#log-follow').textContent=`Auto-scroll: ${followLogs?'on':'off'}`;if(followLogs)$('#log-lines').scrollTop=$('#log-lines').scrollHeight;});
$('#copy-logs').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('#log-lines').innerText);toast('Console output copied');}catch{toast('Copy is unavailable. Select the console text to copy it.',true);}});
async function api(path, body) {
  const response=await fetch(path, body===undefined?{credentials:'same-origin'}:{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok) { if(response.status===401 && path!='/api/login') showLogin('Your session expired or the portal restarted. Sign in again.'); throw new Error(result.error || 'Request failed'); }
  return result;
}
function showLogin(message='') {sessionEpoch++;currentUser=null;jsonLoadVersion++;logLoadVersion++;document.querySelectorAll('dialog[open]').forEach(d=>d.close()); $('#shell').hidden=true; $('#login').hidden=false; $('#login-error').textContent=message;}
function uptime(seconds) { if(!seconds) return '—'; const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60); return h?`${h}h ${m}m`:`${m}m ${seconds%60}s`; }
function selectOptions(selector) { const el=$(selector), old=el.value,bots=state.bots.filter(b=>selector==='#log-bot'?canBot(b,'logs'):canBot(b,'cogs')||canBot(b,'settings.read')); el.innerHTML=bots.map(b=>`<option value="${b.id}">${escapeHTML(b.name)}</option>`).join(''); if(bots.some(b=>b.id===old)) el.value=old; }
function render() {
  const running=state.bots.filter(b=>b.status==='running').length;
  const stats=[['Total bots',state.bots.length,'Your managed fleet','◈'],['Running',running,`${state.bots.length-running} offline or connecting`,'◉'],['Loaded cogs',state.bots.reduce((n,b)=>n+b.loaded.length,0),'Across active bots','▦'],['Cog library',state.cogs.length,`${state.cogs.filter(c=>c.kind==='custom').length} custom modules`,'⌘']];
  $('#stats').innerHTML=stats.map(([title,value,note,icon])=>`<div class="stat"><div class="stat-top">${title}<span class="stat-icon">${icon}</span></div><strong>${value}</strong><small>${note}</small></div>`).join('');
  $('#fleet').innerHTML=state.bots.length?state.bots.map(b=>{
    const active=['running','starting','stopping'].includes(b.status);
    return `<article class="bot-card" data-card="${b.id}" tabindex="0" aria-label="Open ${escapeHTML(b.name)} portal"><div class="bot-top"><div class="avatar">${escapeHTML(b.name[0].toUpperCase())}</div><div><h2><a data-link href="/bots/${b.id}">${escapeHTML(b.name)}</a></h2><p>${b.mode==='demo'?'Demo runtime':b.mode==='redbot'?'Redbot runtime':'Discord runtime'} · ${escapeHTML(b.prefix)} commands</p>${b.phase?`<p>${escapeHTML(b.phase)}</p>`:''}</div><span class="badge ${b.status}">${b.status}</span></div><div class="bot-details"><div><span>UPTIME</span>${uptime(b.uptime)}</div><div><span>LOADED COGS</span>${b.loaded.length} / ${b.enabled_cogs.length}</div><div><span>SERVERS</span>${b.mode==='demo'?'Demo':b.guilds}</div></div><div class="bot-actions"><button class="${active?'secondary':'primary'}" data-bot="${b.id}" data-action="${active?'stop':'start'}">${active?'■ Stop':'▶ Start'}</button><button class="secondary" data-bot="${b.id}" data-action="restart" ${active?'':'disabled'}>↻ Restart</button><a data-link class="portal-button" href="/bots/${b.id}">Open portal</a><button class="secondary" data-bot="${b.id}" data-action="manage">Cogs</button><button class="more" data-bot="${b.id}" data-action="edit" ${active?'disabled':''}>Settings</button><button class="danger" data-bot="${b.id}" data-action="delete" ${active?'disabled':''}>Delete</button></div></article>`;
  }).join(''):'<div class="empty"><div class="stat-icon">◈</div><h2>Your fleet starts here.</h2><p>Create a demo bot to explore, or connect your Discord bot.</p><button class="primary" id="empty-create">+ Create your first bot</button></div>';
  selectOptions('#cog-bot'); selectOptions('#log-bot'); renderRoute();if(!route.botId)filterFleet();$('#signed-in-user').textContent=`${currentUser.username} / ${currentUser.role==='admin'?'Administrator':'Member'}`;
  $('#admin-nav').hidden=currentUser?.role!=='admin';
  $('#new-bot').hidden=!canSite('bots.create');$('#import-bot').hidden=!canSite('bots.import');$('#upload-cog').hidden=!canSite('cogs.upload');
  $('#empty-create')?.toggleAttribute('hidden',!canSite('bots.create'));
  document.querySelectorAll('[data-bot][data-action]').forEach(button=>{const bot=state.bots.find(b=>b.id===button.dataset.bot),p={start:'control',stop:'control',restart:'control',manage:'cogs',edit:'configure',delete:'delete'}[button.dataset.action];if(p&&!canBot(bot,p))button.disabled=true;});
}
function renderCogs() {
  const bot=state.bots.find(b=>b.id===$('#cog-bot').value);
  $('#cog-list').innerHTML=(bot?.cog_catalog || state.cogs).map(c=>{
    const loaded=bot?.loaded.includes(c.module), enabled=bot?.enabled_cogs.includes(c.module), ready=bot?.status==='running'&&!c.settings_only&&canBot(bot,'cogs');
    return `<article class="cog-card"><div class="avatar">▦</div><div class="cog-copy"><h3>${escapeHTML(c.name)}</h3><p>${escapeHTML(c.module)} · ${escapeHTML(c.kind)} · ${c.settings_only?'Saved native cog data':enabled?'Enabled on startup':'Not enabled on startup'}</p></div>${c.settings_only?'':`<span class="badge ${loaded?'':'stopped'}">${loaded?'Loaded':'Stopped'}</span><button class="${loaded?'secondary':'primary'}" data-module="${escapeHTML(c.module)}" data-cog-action="${loaded?'unload':'load'}" ${ready?'':'disabled'}>${loaded?'Stop':'Start'}</button><button class="secondary" data-module="${escapeHTML(c.module)}" data-cog-action="reload" ${ready&&loaded?'':'disabled'}>↻ Reload</button>`}${c.has_settings===false?'':`<button class="secondary" data-module="${escapeHTML(c.module)}" data-cog-action="settings" ${bot&&canBot(bot,'settings.read')?'':'disabled'}>JSON settings</button>`}</article>`;
  }).join('');
  if(!bot) $('#cog-list').insertAdjacentHTML('afterbegin','<p class="form-note">Create a bot first to use cog controls.</p>');
  else if(bot.mode==='demo') $('#cog-list').insertAdjacentHTML('afterbegin','<p class="form-note">Demo mode simulates cog controls. Switch to Discord to execute cog code.</p>');
  else if(bot.mode==='redbot') $('#cog-list').insertAdjacentHTML('afterbegin','<p class="form-note">Native Redbot cogs and saved data. Stop the bot before editing its JSON settings. Redbot cog uploads belong in its managed CogManager/cogs folder.</p>');
}
async function refresh(force=false) {
  if(busy || (refreshing&&!force)) return;
  refreshing=true;
  const epoch=sessionEpoch, version=++stateRequestVersion;
  try {const result=await api('/api/state');if(epoch!==sessionEpoch||version!==stateRequestVersion)return;state=result;if(!state.user){showLogin('Restart the BotManager process to activate accounts and permissions.');return;}currentUser=state.user; $('#login').hidden=true; $('#shell').hidden=false; render(); $('#refresh-status').textContent='Live · refreshes every 3s'; }
  catch(e) { if(!$('#shell').hidden) $('#refresh-status').textContent='Connection lost · retrying'; }
  finally {if(version===stateRequestVersion)refreshing=false;}
}
async function refreshLogs() {
  const id=route.botId || $('#log-bot').value, version=++logLoadVersion;
  if(!id) { $('#log-lines').textContent='Create a bot to see its activity.'; return; }
  const result=await api(`/api/bots/${id}/logs`);
  if(version!==logLoadVersion || view!=='logs') return;
  const el=$('#log-lines'), nearBottom=el.scrollHeight-el.scrollTop-el.clientHeight<50;
  el.innerHTML=result.logs.length?result.logs.map(l=>`<div class="log-line ${l.level==='error'?'log-error':''}"><span class="log-time">${escapeHTML(l.time)}</span>${escapeHTML(l.message)}</div>`).join(''):'<span class="log-time">No activity yet. Start this bot to see runtime events.</span>';
  if(followLogs&&nearBottom) el.scrollTop=el.scrollHeight;
}
function switchView(next) {
  navigate({overview:'/',cogs:'/cogs',logs:'/logs',admin:'/admin'}[next] || '/');
}
function navigate(path) {
  if(location.pathname!==path) history.pushState(null,'',path);
  route=PortalRoutes.parseRoute(location.pathname);
  jsonTarget=null; jsonLoadVersion++; logLoadVersion++;
  document.querySelectorAll('dialog[open]').forEach(d=>d.close());
  if(!$('#shell').hidden) render();
}
function renderRoute() {
  view=route.view;
  const bot=state.bots.find(b=>b.id===route.botId);
  if(route.botId && !bot) view='notfound';
  const required={logs:'logs',settings:'configure',cogsettings:'settings.read'}[view];
  if(bot&&((required&&!canBot(bot,required))||(view==='cogs'&&!canBot(bot,'cogs')&&!canBot(bot,'settings.read'))))view='forbidden';
  if(!bot&&((view==='admin'&&currentUser?.role!=='admin')||(view==='create'&&!canSite('bots.create'))||(view==='import'&&!canSite('bots.import'))||(view==='upload'&&!canSite('cogs.upload'))))view='forbidden';
  for(const name of ['overview','cogs','logs','bot-settings','cog-settings','notfound','admin','forbidden']) $(`#${name}-view`).hidden=true;
  $('#bot-portal').hidden=!bot; $('#workspace-tabs').hidden=!!route.botId;
  $('#stats').hidden=!!route.botId || view==='notfound';
  $('#overview-view').classList.toggle('bot-home',!!bot);$('.fleet-tools').hidden=!!route.botId;
  $('.intro-actions').hidden=!!route.botId;
  $('#cog-bot').closest('label').hidden=!!route.botId; $('#log-bot').hidden=!!route.botId;
  document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',!route.botId && b.dataset.view===view));
  if(bot) {
    $('#page-title').textContent=bot.name; $('#page-subtitle').textContent=`${bot.mode==='redbot'?'Redbot':bot.mode==='demo'?'Demo':'Discord'} runtime · ${bot.prefix} commands`;
    const label={bot:'Overview',logs:'Console',cogs:'Cogs',settings:'Settings',cogsettings:'Cog settings'}[view]||'Overview';
    $('#breadcrumb').textContent=`Workspace / ${bot.name} / ${label}`;
    const base=`/bots/${bot.id}`, active=['running','starting','stopping'].includes(bot.status);
    $('#bot-summary').innerHTML=`<div class="bot-header"><div><span class="badge ${bot.status}">${bot.status}</span><p>${escapeHTML(bot.phase||'Process stopped')} · Uptime ${uptime(bot.uptime)} · ${bot.loaded.length} loaded cogs · ${bot.guilds} servers</p></div><div class="bot-actions"><button class="primary" data-bot="${bot.id}" data-action="${active?'stop':'start'}">${active?'Stop bot':'Start bot'}</button><button class="secondary" data-bot="${bot.id}" data-action="restart" ${active?'':'disabled'}>Restart</button></div></div>`;
    $('#bot-tabs').innerHTML=[['bot','Overview',base],['logs','Console',`${base}/console`],['cogs','Cogs',`${base}/cogs`],['settings','Settings',`${base}/settings`]].filter(([key])=>key==='bot'||(key==='logs'&&canBot(bot,'logs'))||(key==='cogs'&&(canBot(bot,'cogs')||canBot(bot,'settings.read')))||(key==='settings'&&canBot(bot,'configure'))).map(([key,text,path])=>`<a data-link href="${path}" class="${view===key||(key==='cogs'&&view==='cogsettings')?'active':''}">${text}</a>`).join('');
    $('#cog-bot').value=bot.id; $('#log-bot').value=bot.id;
    if(view==='bot') {
      $('#overview-view').hidden=false;
      $('#fleet').innerHTML=`<article class="bot-card"><h2>At a glance</h2><div class="bot-details"><div><span>RUNTIME</span>${escapeHTML(bot.mode)}</div><div><span>COMMAND PREFIX</span>${escapeHTML(bot.prefix)}</div><div><span>ENABLED COGS</span>${bot.enabled_cogs.length}</div></div><p>${bot.mode==='demo'?'Demo controls are simulated.':'This bot has its own process, cog controls, settings, and live console.'}</p><div class="portal-links"><a data-link href="${base}/console">Open console →</a><a data-link href="${base}/cogs">Manage cogs →</a><a data-link href="${base}/settings">Edit settings →</a></div></article>`;
      $('#overview-view .tip').hidden=true;
    } else if(view==='settings') {
      $('#bot-settings-view').hidden=false; renderBotSettings(bot);
    } else if(view==='cogsettings') {
      $('#cog-settings-view').hidden=false; loadCogSettings(bot,route.module);
    }
  } else {
    const names={overview:['Overview','Your bots, in sync.','Choose a bot to open its control portal.'],cogs:['Cog library','Make it modular.','Manage capabilities across your fleet.'],logs:['Activity logs','Know what’s happening.','A clear view into every bot process.']};
    const [label,title,subtitle]=names[view]||names.overview;
    $('#breadcrumb').textContent=`Workspace / ${label}`; $('#page-title').textContent=title; $('#page-subtitle').textContent=subtitle;
    $('#overview-view .tip').hidden=false;
  }
  document.title=bot?`${bot.name} · BotManager`:'BotManager · Control room';
  if(['overview','cogs','logs','notfound','admin','forbidden'].includes(view)) $(`#${view}-view`).hidden=false;
  if(view==='admin'){ $('#page-title').textContent='Accounts & permissions';$('#page-subtitle').textContent='Control who can access your workspace and bots.';if(typeof loadAccounts==='function'&&!adminData)loadAccounts(); }
  renderCogs();
  if(view==='logs') refreshLogs().catch(e=>toast(e.message,true));
  if(view==='create') { $('#overview-view').hidden=false; if(!$('#bot-dialog').open) botDialog(); }
  if(view==='import') { $('#overview-view').hidden=false; if(!$('#import-dialog').open) $('#import-dialog').showModal(); }
  if(view==='upload') { $('#cogs-view').hidden=false; if(!$('#upload-dialog').open) openUpload(); }
  if(bot&&view==='cogsettings'){const disabled=!canBot(bot,'settings.write')||(bot.mode==='redbot'&&['running','starting','stopping'].includes(bot.status));for(const el of $('#cog-page-form').elements)el.disabled=disabled;}
}
function renderBotSettings(bot) {
  const form=$('#bot-page-form'), active=['running','starting','stopping'].includes(bot.status);
  if(pageSettingsBotId!==bot.id || !pageSettingsDirty) {
    form.elements.name.value=bot.name; form.elements.prefix.value=bot.prefix; form.elements.token.value='';
    form.elements.red_co_owner_ids.value=(bot.red_co_owner_ids||[]).join(', ');
    pageSettingsBotId=bot.id; pageSettingsDirty=false;
  }
  $('#page-co-owners').hidden=bot.mode!=='redbot';
  for(const element of form.elements) element.disabled=active;
  $('#bot-settings-note').textContent=active?'Stop the bot using the controls above to edit its settings.':'Changes persist in JSON and apply at the next start.';
}
async function loadCogSettings(bot,module) {
  const key=`${bot.id}/${module}`;
  if(jsonTarget===key) return;
  jsonTarget=key; const version=++jsonLoadVersion;
  const form=$('#cog-page-form'); form.elements.settings.value='';
  form.querySelector('button').disabled=true; $('#cog-page-title').textContent=`${module} settings`;
  try {
    const result=await api(`/api/bots/${bot.id}/settings/${module}`);
    if(version!==jsonLoadVersion) { if(jsonTarget===key) jsonTarget=null; return; }
    form.elements.settings.value=JSON.stringify(result.settings,null,2);const disabled=!canBot(bot,'settings.write')||(bot.mode==='redbot'&&['running','starting','stopping'].includes(bot.status));for(const el of form.elements)el.disabled=disabled;
  } catch(e) { if(version===jsonLoadVersion) { jsonTarget=null; toast(e.message,true); } }
}
function openUpload() { $('#upload-form').reset(); $('#upload-form').elements.source.value=template; $('#upload-form').elements.name.value='welcome'; $('#upload-dialog').showModal(); }
window.addEventListener('popstate',()=>{route=PortalRoutes.parseRoute(location.pathname);jsonTarget=null;jsonLoadVersion++;logLoadVersion++;if(!$('#shell').hidden)render();});
document.addEventListener('click',e=>{const link=e.target.closest('a[data-link]');if(link&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&e.button===0){e.preventDefault();navigate(link.getAttribute('href'));}});
document.addEventListener('click',e=>{const card=e.target.closest('[data-card]');if(card&&!e.target.closest('a,button,input,select'))navigate(`/bots/${card.dataset.card}`);});
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.matches('[data-card]'))navigate(`/bots/${e.target.dataset.card}`);});
for(const [id,name] of [['bot-dialog','create'],['import-dialog','import'],['upload-dialog','upload']]) $(`#${id}`).addEventListener('cancel',()=>{if(route.view===name)navigate(name==='upload'?'/cogs':'/');});
function botDialog(bot) {
  $('#redbot-option').hidden=bot?.mode!=='redbot';
  $('#redbot-owner-fields').hidden=bot?.mode!=='redbot';
  const form=$('#bot-form'); form.reset(); form.elements.id.value=bot?.id||''; form.elements.name.value=bot?.name||''; form.elements.mode.value=bot?.mode||'demo'; form.elements.prefix.value=bot?.prefix||'!'; $('#bot-form-title').textContent=bot?'Bot settings':'Create a bot'; $('#bot-dialog').showModal();
  form.elements.red_co_owner_ids.value=(bot?.red_co_owner_ids||[]).join(', ');
}
async function perform(fn, message) { if(busy) return; busy=true; document.body.setAttribute('aria-busy','true');const form=document.querySelector('dialog[open] form')||document.activeElement?.closest('form');const submit=form?.querySelector('[type=submit]');if(submit){submit.disabled=true;submit.classList.add('loading');}try { await fn(); if(message) toast(message); } catch(e) { toast(e.message,true); } finally { busy=false; document.body.removeAttribute('aria-busy');if(submit){submit.disabled=false;submit.classList.remove('loading');} await refresh(); } }
document.addEventListener('click',async event=>{
  const button=event.target.closest('button'); if(!button) return;
  if(button.id==='reset-fleet-filter'){$('#fleet-search').value='';$('#fleet-status').value='all';filterFleet();return;}
  if(button.dataset.close) { $(`#${button.dataset.close}`).close(); if(['create','import','upload'].includes(route.view)) navigate(route.view==='upload'?'/cogs':'/'); return; }
  if(button.dataset.view) return switchView(button.dataset.view);
  if(['new-bot','empty-create'].includes(button.id)) return navigate('/bots/new');
  if(button.dataset.bot) {
    const id=button.dataset.bot, action=button.dataset.action, bot=state.bots.find(b=>b.id===id);
    if(action==='edit') return navigate(`/bots/${id}/settings`);
    if(action==='manage') return navigate(`/bots/${id}/cogs`);
    if(action==='delete' && !(await confirmAction(`Delete ${bot.name}?`,'This removes the bot from your fleet. Saved cog data will remain on disk.'))) return;
    return perform(async()=>{await api(`/api/bots/${id}/${action}`,{});if(action==='delete')navigate('/');},`${action==='delete'?'Bot deleted':action==='start'?'Bot starting':action==='stop'?'Bot stopped':'Bot restarting'}`);
  }
  if(button.dataset.cogAction) {
    const module=button.dataset.module, action=button.dataset.cogAction, id=$('#cog-bot').value;
    if(action==='settings') {
      jsonTarget=null; return navigate(`/bots/${id}/cogs/${encodeURIComponent(module)}/settings`);
    }
    return perform(()=>api(`/api/bots/${id}/cogs`,{module,action}),`Cog ${action==='load'?'started':action==='unload'?'stopped':'reloaded'}`);
  }
});
$('#login-form').addEventListener('submit',async e=>{e.preventDefault(); try {const result=await api('/api/login',{username:e.target.elements.username.value,password:e.target.elements.password.value});e.target.reset();if(!result.user)throw new Error('Restart the BotManager process to activate accounts and permissions.');sessionEpoch++;currentUser=result.user;$('#login-error').textContent='';if(typeof adminData!=='undefined')adminData=null;await refresh(true);} catch(error){$('#login-error').textContent=error.message;}});
$('#logout').addEventListener('click',async()=>{try{await api('/api/logout',{});currentUser=null;showLogin();}catch(e){toast(e.message,true);}});
$('#bot-form').addEventListener('submit',e=>{e.preventDefault();const payload=Object.fromEntries(new FormData(e.target)),id=payload.id;delete payload.id;perform(async()=>{const result=await api(id?`/api/bots/${id}/save`:'/api/bots',payload);$('#bot-dialog').close();navigate(`/bots/${id||result.id}`);},'Bot settings saved');});
const template=`import discord\nfrom discord.ext import commands\n\nclass Welcome(commands.Cog):\n    def __init__(self, bot):\n        self.bot = bot\n\n    @commands.command()\n    async def welcome(self, ctx):\n        settings = self.bot.cog_store("custom_cogs.welcome").read()\n        await ctx.send(settings.get("message", "Welcome aboard!"), allowed_mentions=discord.AllowedMentions.none())\n\nasync def setup(bot):\n    await bot.add_cog(Welcome(bot))\n`;
$('#upload-cog').addEventListener('click',()=>navigate('/cogs/new'));
$('#cog-file').addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;if(file.size>200000)return toast('File must be under 200 KB',true);$('#upload-form').elements.source.value=await file.text();$('#upload-form').elements.name.value=file.name.replace(/\.py$/i,'');});
$('#upload-form').addEventListener('submit',e=>{e.preventDefault();const form=e.target;perform(async()=>{await api('/api/cogs',{name:form.elements.name.value,source:form.elements.source.value});$('#upload-dialog').close();navigate('/cogs');},'Custom cog added to library');});
$('#settings-form').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{const settings=JSON.parse(e.target.elements.settings.value);if(!settings||typeof settings!=='object'||Array.isArray(settings))throw new Error('Settings must be a JSON object');await api(`/api/bots/${settingTarget.id}/settings/${settingTarget.module}`,{settings});$('#settings-dialog').close();},'JSON settings saved');});
$('#import-bot').addEventListener('click',()=>navigate('/bots/import'));
$('#import-form').addEventListener('submit',e=>{e.preventDefault();const form=e.target;toast('Importing full bot data and libraries. This may take a minute.');perform(async()=>{const result=await api('/api/import',{path:form.elements.path.value,python:form.elements.python.value||undefined});$('#import-dialog').close();navigate(`/bots/${result.id}`);},'Redbot imported. Start it when ready.');});
$('#bot-page-form').addEventListener('input',()=>pageSettingsDirty=true);
$('#bot-page-form').addEventListener('submit',e=>{e.preventDefault();const id=route.botId,payload=Object.fromEntries(new FormData(e.target));perform(async()=>{await api(`/api/bots/${id}/save`,payload);pageSettingsDirty=false;},'Bot settings saved');});
$('#cog-page-form').addEventListener('submit',e=>{e.preventDefault();const id=route.botId,module=route.module;perform(async()=>{const settings=JSON.parse(e.target.elements.settings.value);if(!settings||typeof settings!=='object'||Array.isArray(settings))throw new Error('Settings must be a JSON object');await api(`/api/bots/${id}/settings/${module}`,{settings});},'JSON settings saved');});
$('#cog-bot').addEventListener('change',renderCogs); $('#log-bot').addEventListener('change',()=>refreshLogs().catch(e=>toast(e.message,true)));
$('#login-form button[type="submit"]').disabled=false;
const initialSessionEpoch=sessionEpoch;
api('/api/session').then(session=>{if(sessionEpoch!==initialSessionEpoch)return;if(session.authenticated){currentUser=session.user;refresh();}else showLogin();}).catch(()=>{if(sessionEpoch===initialSessionEpoch)refresh();});
setInterval(()=>{if(!$('#shell').hidden)refresh();},3000);

for(const dialog of document.querySelectorAll('dialog')) {
  const heading=dialog.querySelector('h2');if(heading){if(!heading.id)heading.id=`${dialog.id}-title`;dialog.setAttribute('aria-labelledby',heading.id);}
  const sync=()=>document.body.classList.toggle('modal-open',!!document.querySelector('dialog[open]'));
  new MutationObserver(sync).observe(dialog,{attributes:true,attributeFilter:['open']});
  dialog.addEventListener('click',e=>{const rect=dialog.getBoundingClientRect();if(e.target===dialog&&(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)){const close=dialog.querySelector('[data-close]');if(close)close.click();}});
  dialog.addEventListener('close',()=>{sync();if(['create','import','upload'].includes(route.view)&&!document.querySelector('dialog[open]'))navigate(route.view==='upload'?'/cogs':'/');});
}
for(const input of document.querySelectorAll('input[type=password]')){
  const wrap=document.createElement('div');wrap.className='password-field';input.before(wrap);wrap.append(input);
  const toggle=document.createElement('button');toggle.type='button';toggle.className='password-toggle';toggle.textContent='Show';toggle.setAttribute('aria-label','Show password');toggle.setAttribute('aria-pressed','false');wrap.append(toggle);
  toggle.addEventListener('click',()=>{const show=input.type==='password';input.type=show?'text':'password';toggle.textContent=show?'Hide':'Show';toggle.setAttribute('aria-label',`${show?'Hide':'Show'} password`);toggle.setAttribute('aria-pressed',String(show));});
  input.form?.addEventListener('reset',()=>{input.type='password';toggle.textContent='Show';toggle.setAttribute('aria-label','Show password');toggle.setAttribute('aria-pressed','false');});
}
