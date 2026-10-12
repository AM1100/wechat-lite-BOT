"use strict";
let config, version, csrf, poll;
const $ = selector => document.querySelector(selector);
function notify(message, error=false) {
  const box=$('#notice'); box.textContent=message;box.classList.toggle('error',error);box.hidden=false;
  clearTimeout(notify.timer);notify.timer=setTimeout(()=>box.hidden=true,error?15000:6500);
}
async function request(url, body) {
  const options={credentials:'same-origin',headers:{}};
  if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.headers['X-CSRF-Token']=csrf||'';options.body=JSON.stringify(body);}
  const response=await fetch(url,options);
  const value=await response.json();
  if(!response.ok){if(response.status===401 && url!=='/api/login')showLogin();throw new Error(value.error||'请求失败');}
  return value;
}
function valueAt(object,path){return path.split('.').reduce((o,k)=>o?.[k],object);}
function setAt(object,path,value){const keys=path.split('.');let target=object;keys.slice(0,-1).forEach(k=>target=target[k]);target[keys.at(-1)]=value;}
function fill() {
  document.querySelectorAll('[data-field]').forEach(input=>{
    const value=valueAt(config,input.dataset.field)??(input.dataset.field==='model_concurrency'?2:'');
    if(input.type==='checkbox')input.checked=Boolean(value);else input.value=value??'';
  });
  $('#api-key').value='';$('#key-status').textContent=config.model.api_key_set?'已保存 Key；留空表示不更换。':'尚未保存 Key，请填写。';
  $('#extra-body').value=JSON.stringify(config.model.extra_body||{},null,2);renderFriends();
}
function collect(){
  const result=structuredClone(config);
  document.querySelectorAll('[data-field]').forEach(input=>{
    let value=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;
    setAt(result,input.dataset.field,value);
  });
  result.model.api_key=$('#api-key').value.trim();
  try{result.model.extra_body=JSON.parse($('#extra-body').value||'{}');}catch{throw new Error('附加参数不是有效的 JSON。');}
  return result;
}
function renderFriends(){
  const list=$('#friend-list');list.replaceChildren();$('#friend-count').textContent=config.allowed_private_chats.length+' 位好友';
  if(!config.allowed_private_chats.length){const empty=document.createElement('p');empty.className='empty';empty.textContent='还没有添加好友。只有白名单里的私聊会收到回复。';list.append(empty);}
  config.allowed_private_chats.forEach(name=>{
    const chip=document.createElement('div');chip.className='friend';const text=document.createElement('span');text.textContent=name;
    const remove=document.createElement('button');remove.textContent='×';remove.setAttribute('aria-label','移除 '+name);
    remove.onclick=()=>{config.allowed_private_chats=config.allowed_private_chats.filter(n=>n!==name);renderFriends();};chip.append(text,remove);list.append(chip);
  });
}
function sampleInfo(sample){$('#sample-info').textContent=sample?`${sample.filename} · ${sample.chars} 字 · ${sample.lines} 条文字片段`:'尚未导入样本';}
function status(value){
  const labels={running:'监听中',waiting:'等待处理',stopped:'已停止',stale:'状态未更新',unknown:'等待启动'};
  $('#state').textContent=value.state==='running'?(value.enabled===false?'已暂停':value.dry_run?'仅监听':'自动回复'):labels[value.state]||value.state;
  $('#chat').textContent=value.rotation_active?`${value.friend_count||0} 位好友轮流监听`:(value.chat||'—');
  $('#calls').textContent=value.today_calls??0;
  const queue=value.queue_friends===undefined?'':` · 等待回复 ${value.queue_friends} 人 · 模型处理中 ${value.model_jobs||0} · 待发送 ${value.ready_replies||0} · 等待发送确认 ${value.pending_confirmation||0}`;
  $('#event').textContent=(value.event||'等待机器人状态')+queue;sampleInfo(value.sample);
}
function showLogin(){clearInterval(poll);$('#dashboard').hidden=true;$('#login').hidden=false;}
async function load(){const value=await request('/api/state');config=value.config;version=value.version;csrf=value.csrf;fill();status(value.status);$('#login').hidden=true;$('#dashboard').hidden=false;clearInterval(poll);poll=setInterval(()=>request('/api/status').then(status).catch(()=>{}),10000);}
async function busy(button, action, message){const old=button.textContent;button.disabled=true;button.textContent=message;try{await action();}catch(error){notify(error.message,true);}finally{button.disabled=false;button.textContent=old;}}
$('#login-form').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{await request('/api/login',{username:$('#username').value,password:$('#password').value});$('#password').value='';await load();},'正在登录…');};
$('#logout').onclick=async()=>{try{await request('/api/logout',{});showLogin();}catch(error){notify(error.message,true);}};
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{
  document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b===button));
  document.querySelectorAll('.panel').forEach(panel=>panel.hidden=panel.id!=='tab-'+button.dataset.tab);
  $('#page-title').textContent=button.querySelector('span').textContent;
});
$('#save').onclick=()=>busy($('#save'),async()=>{const result=await request('/api/config',{version,config:collect()});config=result.config;version=result.version;fill();notify('设置已保存。稍等监听就绪后，再发新消息测试。');},'正在保存…');
$('#friend-form').onsubmit=event=>{event.preventDefault();const name=$('#friend-name').value.trim();if(!name)return;if(config.allowed_private_chats.includes(name))return notify('这个好友已在白名单里。',true);config.allowed_private_chats.push(name);$('#friend-name').value='';renderFriends();notify('已加入列表，点击右上角保存后生效。');};
$('#test-model').onclick=()=>busy($('#test-model'),async()=>{const result=await request('/api/test',{});notify('接口连接成功：'+result.reply);},'正在测试已保存的接口…');
$('#sample-file').onchange=async()=>{
  const file=$('#sample-file').files[0];if(!file)return;
  if(file.size>500000){notify('文件超过500KB，请拆分后上传。',true);return;}
  try{
    const bytes=await file.arrayBuffer();let text;
    try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{text=new TextDecoder('gb18030',{fatal:true}).decode(bytes);}
    const result=await request('/api/sample',{filename:file.name,text});sampleInfo(result.sample);$('#preview-box').hidden=false;$('#sample-preview').textContent=result.preview;notify('文字样本已导入。点击提炼风格后才会调用模型。');
  }catch(error){notify(error.message,true);}
};
$('#analyze').onclick=()=>busy($('#analyze'),async()=>{
  const result=await request('/api/style/analyze',{});$('[data-field="model.style_profile"]').value=result.profile;
  notify(`风格已生成（分析 ${result.sample_chars} 字样本）。检查后点击右上角保存。`);
},'正在提炼风格，请稍等…');
$('#delete-sample').onclick=()=>busy($('#delete-sample'),async()=>{await request('/api/sample/delete',{});sampleInfo(null);$('#preview-box').hidden=true;$('#sample-file').value='';notify('原始样本已删除，已保存的风格描述仍保留。');},'正在删除…');
$('#password-form').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{await request('/api/password',{password:$('#new-password').value});$('#new-password').value='';showLogin();notify('密码已更换，请重新登录。');},'正在更换…');};
load().catch(error=>{showLogin();if(error.message!=='请先登录。')notify(error.message,true);});
