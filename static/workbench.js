/* 直播工作台：主页面现有布局、朗读、WebSocket 共用状态。 */
(() => {
  const E = esc;
  const pending = new Map();
  let seq = 0, libPage = 0, importRows = [];
  const modal = (id, title, html) => {
    const d = document.createElement('dialog'); d.id = id; d.className = 'wb-dialog';
    d.innerHTML = `<header><h2>${title}</h2><button class="btn sm" data-wb-close>关闭</button></header><div class="wb-body">${html}</div>`;
    d.addEventListener('click', e => { if (e.target.closest('[data-wb-close]')) d.close(); });
    document.body.append(d); return d;
  };
  const library = modal('wb-library', '我的曲库', `
    <div class="wb-toolbar"><input id="lib-search" placeholder="搜索歌名、歌手、标签或备注" aria-label="搜索曲库"><select id="lib-level" aria-label="熟练度筛选"><option value="">全部熟练度</option><option>待整理</option><option>练习中</option><option>熟悉</option><option>拿手</option></select><select id="lib-available" aria-label="点歌状态筛选"><option value="">全部状态</option><option value="yes">开放点歌</option><option value="no">暂停点歌</option></select><select id="lib-sort" aria-label="曲库排序"><option value="recent">最近唱过</option><option value="count">演唱次数</option><option value="name">歌名</option></select></div>
    <div class="wb-toolbar"><button class="btn accent" id="lib-new" title="新增一首">＋</button><button class="btn" id="lib-import" title="批量导入：JSON、CSV 或从表格复制">${icon('download')}</button><button class="btn" id="lib-export" title="导出成文件">${icon('upload')}</button><span id="lib-count" class="wb-sub" style="margin:0"></span></div>
    <div class="wb-modal-table" id="lib-table"></div><div class="wb-footer"><button class="btn sm" id="lib-prev">上一页</button><span id="lib-page"></span><button class="btn sm" id="lib-next">下一页</button></div><div class="wb-status" id="lib-status" role="status"></div>`);
  const editor = modal('wb-editor', '歌曲资料', `
    <form id="lib-form"><div class="wb-grid">
      <label class="wb-field">歌名<input id="lf-name" required maxlength="80"></label><label class="wb-field">歌手<input id="lf-artist" maxlength="80" placeholder="例如：周杰伦"></label>
      <label class="wb-field">标签（逗号分隔）<input id="lf-tags" placeholder="华语，抒情，夜晚"></label><label class="wb-field">熟练度<select id="lf-level"><option>待整理</option><option>练习中</option><option>熟悉</option><option>拿手</option></select></label>
      <label class="wb-field">演唱调号<input id="lf-key" maxlength="24" placeholder="例如：原调 / C / 降 2"></label><label class="wb-field">点歌状态<select id="lf-available"><option value="yes">开放点歌</option><option value="no">暂停点歌</option></select></label>
      <label class="wb-field wide">伴奏链接<input id="lf-backing" type="url" maxlength="1500" placeholder="https://…"></label><label class="wb-field wide">演唱备注<textarea id="lf-note" maxlength="1000" placeholder="起音、换气、需要注意的段落"></textarea></label><label class="wb-field wide">歌词 / 谱子<textarea id="lf-lyrics" maxlength="8000" rows="6" placeholder="贴歌词，或者谱子的网址（图片网址会直接显示）。唱的时候歌单里点「词」打开提词小窗"></textarea></label>
    </div><p class="wb-sub" id="lf-history"></p><div id="lf-status" class="wb-status" role="status"></div><div class="wb-footer"><button type="button" class="btn" data-wb-close>取消</button><button class="btn accent" type="submit" id="lf-save">保存资料</button></div></form>`);
  const importer = modal('wb-importer', '批量导入曲库', `
    <p class="wb-sub" title="支持导出的 JSON、CSV 或从表格复制的内容；也可以一行一个歌名。同名歌曲只更新资料，演唱次数不变。">列顺序：歌名、歌手、标签、熟练度、调号、伴奏、开放点歌、备注</p>
    <div class="wb-toolbar"><input id="li-file" type="file" accept=".json,.csv,.tsv,.txt" aria-label="选择曲库文件"></div><label class="wb-field">粘贴歌曲<textarea id="li-text" style="min-height:140px" placeholder="晴天&#9;周杰伦&#9;华语,抒情&#9;熟悉"></textarea></label>
    <div class="wb-footer"><button class="btn" id="li-preview">预览导入</button><button class="btn accent" id="li-save" disabled>确认导入</button></div><div id="li-status" class="wb-status" role="status"></div><div class="wb-import-preview" id="li-preview-list" hidden></div>`);
  const preflight = modal('wb-preflight', '开播前自检', `
    <div class="wb-toolbar"><span style="flex:1"></span><button class="btn accent" id="pf-run" title="只检查，不会开始推流，也不会往直播间发消息">↻ 重新检查</button></div>
    <div class="wb-status" id="pf-status" role="status"></div><div class="wb-checks" id="pf-checks"></div><div class="wb-daily" id="pf-daily" title="每天早上 9 点查一次硬盘、备份、隧道、登录；有问题会发 Discord"></div>
    <div class="wb-manual" title="连接成功只能说明上屏页面在线，OBS 场景、麦克风和观众听到的声音要你自己确认"><b>手动确认</b>
    <button class="btn" id="pf-sound" title="用现在的朗读声音读一句">▶ 试听</button>
    <label><input id="pf-heard" type="checkbox"> ${icon('volume')} 试听听到了</label>
    <button class="btn" id="pf-obstest" title="往打开着的 OBS 弹幕页发一条测试弹幕、SC、上舰（只在 OBS 里出现，不进记录）">▶ OBS 测试</button>
    <label><input id="pf-obs" type="checkbox"> ${icon('video')} OBS 弹幕、歌单位置对</label>
    <label><input id="pf-mic" type="checkbox"> ${icon('mic')} 麦克风、伴奏正常</label>
    <div class="wb-status" id="pf-ready" role="status"></div></div>`);

  $('pf-obstest').onclick = () => window._ws?.readyState === 1 && window._ws.send(JSON.stringify({ cmd: 'obs_test' }));
  window.sendWorkbench = (payload) => {
    if (!S.admin || window._ws?.readyState !== WebSocket.OPEN) { note('连接尚未就绪，操作未发送', false); return Promise.resolve(false); }
    const rid = 'wb-' + Date.now() + '-' + ++seq;
    return new Promise(resolve => {
      const timer = setTimeout(() => { pending.delete(rid); note('尚未收到保存确认，请检查连接后再试', false); resolve(false); }, 15000);
      pending.set(rid, {resolve, timer});
      window._ws.send(JSON.stringify({...payload, rid}));
    });
  };
  window.queueSongInput = async text => {
    const old = $('songinput').value;
    if (await sendWorkbench({cmd:'song_add', text})) {
      if ($('songinput').value === old) $('songinput').value = '';
      drawSug();
    }
  };
  window.syncWorkbench = () => { renderLibrary(); };
  window.workbenchMessage = (type, data) => {
    if (type === 'library') { S.library = data; renderLibrary(); window.renderReqs?.(); window.drawLyrics?.(); return true; }
    if (type === 'result' && pending.has(data.rid)) {
      const task = pending.get(data.rid); clearTimeout(task.timer); pending.delete(data.rid);
      note(data.msg, data.ok); $('lib-status').textContent = data.msg; task.resolve(!!data.ok); return true;
    }
    return false;
  };
  const openLibrary = () => { if (!S.admin) return; renderLibrary(); library.showModal(); };
  $('librarybtn').onclick = $('songlibrary').onclick = openLibrary;
  $('songnext').onclick = async () => {
    const button = $('songnext');
    button.disabled = true;
    try {
      await sendWorkbench({cmd:'song_next', expected_now:S.songs?.find(x => x.now)?.id ?? null});
    } finally {
      button.disabled = false;
    }
  };
  document.addEventListener('click', e => { const b=e.target.closest('[data-movesong]'); if(b) {e.stopPropagation(); sendWorkbench({cmd:'song_move',id:b.dataset.movesong,direction:Number(b.dataset.direction)});}}, true);
  function renderLibrary() {
    const q=$('lib-search').value.trim().toLowerCase(), level=$('lib-level').value, avail=$('lib-available').value;
    const rows=(S.library || []).filter(r=>(!q || [r.name,r.artist,...r.tags,r.note].join(' ').toLowerCase().includes(q)) && (!level || r.level===level) && (!avail || r.available===(avail==='yes')));
    rows.sort((a,b)=>$('lib-sort').value==='name' ? a.name.localeCompare(b.name,'zh') : $('lib-sort').value==='count' ? b.n-a.n || a.name.localeCompare(b.name,'zh') : b.last-a.last || a.name.localeCompare(b.name,'zh'));
    const pages=Math.max(1,Math.ceil(rows.length/40)); libPage=Math.min(libPage,pages-1);
    $('lib-count').textContent=`${rows.length} / ${(S.library||[]).length} 首`;
    $('lib-page').textContent=`${libPage+1} / ${pages}`; $('lib-prev').disabled=libPage===0; $('lib-next').disabled=libPage>=pages-1;
    $('lib-table').innerHTML=rows.length ? `<table class="wb-table"><thead><tr><th>歌曲 / 标签</th><th>准备情况</th><th>演唱记录</th><th>操作</th></tr></thead><tbody>${rows.slice(libPage*40,(libPage+1)*40).map(r=>`<tr><td><b>${E(r.name)}</b><small>${E(r.artist||'歌手待补充')}</small>${r.tags.map(t=>`<span class="wb-tag">${E(t)}</span>`).join('')}</td><td>${E(r.level)}${r.key?' · '+E(r.key):''}<small>${r.available?'开放点歌':'暂停点歌'}</small></td><td>${r.n} 次<small>${r.last?fmtDay(r.last):'还没唱过'}</small></td><td><div class="wb-actions"><button class="btn sm" data-lib-add="${E(r.name)}">＋ 排歌</button><button class="btn sm" data-lib-edit="${E(r.name)}">编辑</button>${r.backing && /^https?:\/\//.test(r.backing)?`<a class="btn sm" href="${E(r.backing)}" target="_blank" rel="noopener noreferrer">伴奏 ↗</a>`:''}<button class="btn sm wb-danger" data-lib-delete="${E(r.name)}">删除</button></div></td></tr>`).join('')}</tbody></table>`:'<div class="wb-empty">没有匹配歌曲，试试换个筛选或新增歌曲。</div>';
  }
  for(const id of ['lib-search','lib-level','lib-available','lib-sort']) $(id).addEventListener('input',()=>{libPage=0;renderLibrary();});
  $('lib-prev').onclick=()=>{libPage--;renderLibrary();}; $('lib-next').onclick=()=>{libPage++;renderLibrary();};
  function editSong(name='') {
    const r=(S.library||[]).find(r=>r.name===name)||{name:'',artist:'',tags:[],level:'待整理',key:'',backing:'',available:true,note:'',n:0,last:0};
    for(const field of ['name','artist','level','key','backing','note','lyrics']) $('lf-'+field).value=r[field]||'';
    $('lf-tags').value=r.tags.join('，'); $('lf-available').value=r.available?'yes':'no'; $('lf-name').readOnly=!!name;
    $('lf-history').textContent=name?`已唱 ${r.n} 次${r.last?' · 最近 '+fmtDay(r.last):''}。同一歌名共用资料；其他版本可用「歌名（版本）」另建。`:'';
    $('lf-status').textContent=''; editor.showModal();
  }
  $('lib-new').onclick=()=>editSong();
  $('lib-table').onclick=async e=>{
    const b=e.target.closest('button'); if(!b)return;
    if(b.dataset.libEdit) editSong(b.dataset.libEdit);
    if(b.dataset.libAdd) await sendWorkbench({cmd:'song_add',text:b.dataset.libAdd});
    if(b.dataset.libDelete && confirm(`从曲库删除「${b.dataset.libDelete}」？历史场次保留。`)) await sendWorkbench({cmd:'library_delete',name:b.dataset.libDelete});
  };
  $('lib-form').onsubmit=async e=>{
    e.preventDefault(); const song={}; for(const f of ['name','artist','level','key','backing','note','lyrics'])song[f]=$('lf-'+f).value;
    song.tags=$('lf-tags').value; song.available=$('lf-available').value==='yes'; $('lf-save').disabled=true;
    const ok=await sendWorkbench({cmd:'library_save',song}); $('lf-save').disabled=false;
    if(ok)editor.close(); else $('lf-status').textContent='没有保存成功，请检查填写内容和连接后重试。';
  };
  $('lib-export').onclick=()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify({app:'xiaowu-song-library',version:1,songs:S.library||[]},null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='主播曲库-'+new Date().toISOString().slice(0,10)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);
  };
  function parseDelimited(text, delimiter) {
    const rows=[];let row=[],cell='',quoted=false;
    for(let i=0;i<text.length;i++) {const c=text[i]; if(c==='"'){if(quoted && text[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}
      else if(c===delimiter && !quoted){row.push(cell);cell='';}
      else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell);if(row.some(x=>x.trim()))rows.push(row);row=[];cell='';}
      else cell+=c;}
    if(quoted)throw Error('CSV 引号未闭合');row.push(cell);if(row.some(x=>x.trim()))rows.push(row);return rows;
  }
  function parseImport(text) {
    text=text.replace(/^\uFEFF/,'').trim();if(!text)throw Error('请先粘贴歌曲或选择文件');
    let rows;
    if(/^[\[{]/.test(text)){const j=JSON.parse(text);rows=Array.isArray(j)?j:j.songs;}
    else {const d=text.includes('\t')?'\t':text.includes(',')?',':null;
      let table=d?parseDelimited(text,d):text.split(/\r?\n/).map(x=>[x]);
      if(['歌名','name'].includes(table[0]?.[0]?.trim()))table.shift();
      rows=table.map(r=>({name:r[0]?.trim(),artist:r[1]||'',tags:r[2]||'',level:r[3]||'待整理',key:r[4]||'',backing:r[5]||'',available:!['否','false','0','暂停','暂停点歌'].includes((r[6]||'').trim()),note:r[7]||''}));}
    if(!Array.isArray(rows)||!rows.length||rows.length>3000)throw Error('一次请导入 1–3000 首歌曲');
    const names=new Set();for(const r of rows){if(!r||typeof r!=='object'||typeof r.name!=='string'||!r.name.trim())throw Error('存在空歌名或无效记录');if(r.name.length>80)throw Error('歌名不能超过 80 字');names.add(r.name.trim());}
    return {rows,names:names.size};
  }
  $('lib-import').onclick=()=>importer.showModal();
  const invalidateImport=()=>{importRows=[];$('li-save').disabled=true;$('li-preview-list').hidden=true;};
  $('li-text').oninput=invalidateImport;
  $('li-file').onchange=async e=>{const f=e.target.files[0];if(!f)return;if(f.size>3e6){$('li-status').textContent='文件请小于 3 MB';return;} $('li-text').value=await f.text();invalidateImport();};
  $('li-preview').onclick=()=>{try{const p=parseImport($('li-text').value);importRows=p.rows;const existing=new Set((S.library||[]).map(r=>r.name));const updates=p.rows.filter(r=>existing.has(r.name.trim())).length;
    $('li-status').textContent=`${p.rows.length} 条，${p.names} 个歌名；${updates} 条会更新已有资料。演唱次数不覆盖。`;
    $('li-preview-list').hidden=false;$('li-preview-list').textContent=p.rows.slice(0,100).map(r=>`${r.name} · ${r.artist||'歌手待补充'} · ${r.level||'待整理'}`).join('\n')+(p.rows.length>100?'\n… 仅预览前 100 条':'');$('li-save').disabled=false;
  }catch(e){invalidateImport();$('li-status').textContent=e.message;}};
  $('li-save').onclick=async()=>{if(!importRows.length)return;$('li-save').disabled=true;const ok=await sendWorkbench({cmd:'library_import',rows:importRows});if(ok){importer.close();invalidateImport();}else{$('li-save').disabled=false;$('li-status').textContent='未保存，请检查字段和连接；熟练度应为待整理、练习中、熟悉或拿手。';}};

  // 每种模式保存自己的布局和朗读选择；回到自定义可恢复进入模式前的设置。
  let activeMode='custom', modes={};
  try{activeMode=localStorage.getItem('xw-workmode')||'custom';modes=JSON.parse(localStorage.getItem('xw-workmodes')||'{}');}catch{}
  if(!['custom','sing','chat','moderate'].includes(activeMode))activeMode='custom';
  $('workmode').value=activeMode; window.drawWorkMode?.();
  const modePart=()=>({layout:clone(cfg.layout),tts:clone(cfg.tts),dmFilter:cfg.dmFilter});
  $('workmode').onchange=()=>{
    const next=$('workmode').value;modes[activeMode]=modePart();
    let saved=modes[next];
    if(!saved){
      const templates={sing:[[['req',1.5]], [['dm',1]], [['sc',1],['gift',1]]],chat:[[['dm',1.6]],[['sc',1],['gift',1]],[['users',1],['enter',.8]]],moderate:[[['dm',1.4]],[['users',1],['enter',1]],[['sc',1],['gift',1]]]};
      if(next==='custom')saved=modes.custom||modePart();
      else {const L={cols:templates[next].map((items,i)=>({w:i===0?1.3:1,items:items.map(([id,h])=>({id,h}))})),hidden:Object.keys(PANELS).filter(id=>!templates[next].flat().some(x=>x[0]===id)),tiles:clone(cfg.layout.tiles)};
        saved={layout:L,tts:{...clone(cfg.tts),...(next==='sing'||next==='moderate'?{on:false}:{dm:true,sc:true,gift:true})},dmFilter:'all'};}
    }
    cfg.layout=fixLayout(clone(saved.layout));cfg.tts=merge(DEF.tts,saved.tts);cfg.dmFilter=saved.dmFilter||'all';activeMode=next;
    ttsClear();saveCfg();applyCfg();fillSettings();renderLayout();renderAll();$('dmfilter').value=cfg.dmFilter;
    try{localStorage.setItem('xw-workmode',activeMode);localStorage.setItem('xw-workmodes',JSON.stringify(modes));}catch{}
    note(next==='custom'?'已恢复自定义布局和朗读设置':`已切换${{sing:'唱歌',chat:'聊天',moderate:'房管'}[next]}模式`,true);
  };

  let lastChecks=[], preflightReady=false;
  const readiness=()=>{
    const manual=['pf-heard','pf-obs','pf-mic'].every(id=>$(id).checked);
    const fail=lastChecks.filter(x=>x.status==='fail').length,warn=lastChecks.filter(x=>x.status==='warn').length;
    $('pf-ready').textContent=!preflightReady?'请先完成检查':fail?`还有 ${fail} 项需要处理` : !manual?'请完成上面的声音和 OBS 手动确认':warn?`手动确认已完成；还有 ${warn} 项提醒，请核对后开播`:'检查通过，手动确认已完成';
  };
  async function runPreflight() {
    $('pf-run').disabled=true;preflightReady=false;$('pf-status').textContent='正在检查…';
    try{
      const r=await fetch('/api/preflight',{cache:'no-store',signal:AbortSignal.timeout(10000)});if(!r.ok)throw Error(r.status===403?'需要使用管理页面':'服务器检查失败');
      const data=await r.json();lastChecks=data.checks;
      lastChecks.unshift({title:'管理页面连接',status:window._ws?.readyState===1&&S.admin?'pass':'fail',detail:window._ws?.readyState===1&&S.admin?'WebSocket 在线，具有管理权限':'连接未就绪或缺少管理权限'});
      lastChecks.push({title:'浏览器朗读',status:window.speechSynthesis?'pass':'warn',detail:window.speechSynthesis?'浏览器支持朗读；请点击下方试听确认输出':'当前浏览器不支持朗读'});
      $('pf-checks').innerHTML=lastChecks.map(x=>`<div class="wb-check ${x.status}"><span class="status">${{pass:'通过',warn:'待核对',fail:'需处理'}[x.status]}</span><div><b>${E(x.title)}</b><small>${E(x.detail)}</small></div></div>`).join('');
      $('pf-status').textContent='检查完成 · '+new Date(data.checked_at*1000).toLocaleTimeString();preflightReady=true;
    // 每日体检的结果（后台每天早上查一次）：只列有问题的，全正常就一句话
    const dh=data.daily_health, bad=(dh?.checks||[]).filter(x=>!x.ok);
    $('pf-daily').innerHTML=!dh?.checked_at?'':`<b>每日体检</b><small>${new Date(dh.checked_at*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})}</small>`+(bad.length?bad.map(x=>`<div class="bad">${E(x.detail)}</div>`).join(''):'<div class="ok">硬盘、备份、隧道、登录都正常</div>');
    }catch(e){$('pf-status').textContent=e.message;$('pf-checks').innerHTML='';}
    finally{$('pf-run').disabled=false;readiness();}
  }
  $('preflightbtn').onclick=()=>{for(const id of ['pf-heard','pf-obs','pf-mic'])$(id).checked=false;preflight.showModal();runPreflight();};
  $('pf-run').onclick=runPreflight;
  $('pf-sound').onclick=()=>sayNow('主播，声音测试。祝今天直播顺利。');
  for(const id of ['pf-heard','pf-obs','pf-mic'])$(id).onchange=readiness;
  syncWorkbench();
})();
