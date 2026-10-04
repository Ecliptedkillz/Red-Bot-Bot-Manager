/* Account management. Authenticated APIs enforce every permission independently. */
let adminData=null, adminBusy=false, editingAccount=null;
async function loadAccounts() {
  if(currentUser?.role!=='admin')return;
  try {
    adminData=await api('/api/accounts');
    $('#account-list').innerHTML=adminData.accounts.map(a=>`<article class="account-card"><div><strong>${escapeHTML(a.username)}</strong><p>${a.role==='admin'?'Administrator':'Member'} · ${a.disabled?'Disabled':'Active'}</p></div><button class="secondary" data-edit-account="${a.id}">Permissions / edit</button><button class="danger" data-delete-account="${a.id}" ${a.id===currentUser.id?'disabled':''}>Delete</button></article>`).join('');
  } catch(e){toast(e.message,true);}
}
function permissionChecks(scope,permissions,selected=[]) {
  return Object.entries(permissions).map(([key,label])=>`<label class="permission-check"><input type="checkbox" data-scope="${scope}" value="${key}" ${selected.includes(key)?'checked':''}>${escapeHTML(label)}</label>`).join('');
}
function accountDialog(account=null) {
  editingAccount=account?.id||null;
  const form=$('#account-form');form.reset();
  form.elements.username.value=account?.username||'';form.elements.role.value=account?.role||'member';form.elements.disabled.checked=!!account?.disabled;
  form.elements.password.required=!account;
  $('#account-title').textContent=account?`Edit ${account.username}`:'Create account';
  $('#site-permission-checks').innerHTML=permissionChecks('site',adminData.site_permissions,account?.site_permissions||[]);
  $('#default-permission-checks').innerHTML=permissionChecks('defaults',adminData.bot_permissions,account?.bot_defaults||[]);
  $('#bot-permission-checks').innerHTML=state.bots.map(bot=>{
    const explicit=Object.hasOwn(account?.bot_permissions||{},bot.id);
    const selected=account?.bot_permissions?.[bot.id]||account?.bot_defaults||[];
    return `<fieldset class="bot-permission-group" data-permission-bot="${bot.id}"><legend>${escapeHTML(bot.name)}</legend><label class="permission-check"><input type="checkbox" data-override="${bot.id}" ${explicit?'checked':''}>Use custom permissions for this bot</label><div class="permission-grid" data-bot-checks="${bot.id}">${permissionChecks(bot.id,adminData.bot_permissions,selected)}</div></fieldset>`;
  }).join('');
  updateAccountForm();$('#account-dialog').showModal();
}
function updateAccountForm() {
  const admin=$('#account-form').elements.role.value==='admin';
  $('#account-permissions').hidden=admin;
  document.querySelectorAll('[data-permission-bot]').forEach(group=>{
    const override=group.querySelector('[data-override]').checked;
    group.querySelectorAll('[data-scope]').forEach(input=>input.disabled=!override);
  });
}
document.addEventListener('click',async e=>{
  const edit=e.target.closest('[data-edit-account]'),remove=e.target.closest('[data-delete-account]');
  if(edit)return accountDialog(adminData.accounts.find(a=>a.id===edit.dataset.editAccount));
  if(remove&&(await confirmAction('Delete account?','This permanently removes the account and revokes all its sessions.'))){
    try{await api(`/api/accounts/${remove.dataset.deleteAccount}/delete`,{});await loadAccounts();toast('Account deleted');}catch(error){toast(error.message,true);}
  }
});
$('#new-account').addEventListener('click',()=>accountDialog());
$('#account-form').addEventListener('change',updateAccountForm);
$('#account-form').addEventListener('submit',async e=>{
  e.preventDefault();if(adminBusy)return;adminBusy=true;const submit=e.target.querySelector('[type=submit]');submit.disabled=true;submit.classList.add('loading');
  const form=e.target, selected=scope=>Array.from(form.querySelectorAll('input[data-scope]')).filter(input=>input.dataset.scope===scope&&input.checked).map(input=>input.value);
  const bot_permissions={};form.querySelectorAll('[data-override]:checked').forEach(input=>bot_permissions[input.dataset.override]=selected(input.dataset.override));
  const payload={username:form.elements.username.value,password:form.elements.password.value,role:form.elements.role.value,disabled:form.elements.disabled.checked,
                 site_permissions:selected('site'),bot_defaults:selected('defaults'),bot_permissions};
  try{
    await api(editingAccount?`/api/accounts/${editingAccount}/save`:'/api/accounts',payload);
    $('#account-dialog').close();toast('Account saved. Changed accounts must sign in again.');
    if(editingAccount===currentUser.id){showLogin('Your account changed. Sign in again.');}else await loadAccounts();
  }catch(error){toast(error.message,true);}finally{adminBusy=false;submit.disabled=false;submit.classList.remove('loading');}
});
