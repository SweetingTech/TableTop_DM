const state = { campaigns: [], selectedCampaign: localStorage.getItem('control_campaign_id') || '' };

const $ = (id) => document.getElementById(id);
const showErr = (msg) => { $('error').textContent = msg || ''; };

async function api(url, opts = {}) {
  const r = await fetch(url, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || JSON.stringify(body));
  return body;
}

function tabs() {
  document.querySelectorAll('.tabs button').forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
      $(b.dataset.tab).classList.add('active');
    };
  });
}

async function loadCampaigns() {
  state.campaigns = await api('/api/campaigns');
  $('campaignList').innerHTML = state.campaigns.map((c) => `
    <div>
      <strong>${c.name}</strong> (${c.slug}) [${c.status}/${c.mode}]
      <button onclick="window.control.pickCampaign('${c.id}')">Pick</button>
      <button onclick="window.control.editCampaign('${c.id}')">Edit</button>
      <button onclick="window.control.tombstone('${c.id}')">Tombstone</button>
      <button onclick="window.control.purge('${c.id}')">Purge</button>
    </div>`).join('');
  $('campaignContext').innerHTML = state.campaigns.map((c) => `<option value="${c.id}" ${c.id===state.selectedCampaign?'selected':''}>${c.name}</option>`).join('');
}

async function loadSessions() {
  if (!state.selectedCampaign) return;
  const rows = await api(`/api/campaigns/${state.selectedCampaign}/sessions`);
  $('sessionList').innerHTML = rows.map((s) => `<div>${s.id} ${s.status}
    <button onclick="window.control.sessionAction('${s.id}','pause')">Pause</button>
    <button onclick="window.control.sessionAction('${s.id}','resume')">Resume</button>
    <button onclick="window.control.sessionAction('${s.id}','end')">End</button></div>`).join('');
}

async function loadCharacters() {
  if (!state.selectedCampaign) return;
  const rows = await api(`/api/campaigns/${state.selectedCampaign}/entities`);
  $('characterList').innerHTML = rows.map((e) => `<div>${e.name} (${e.entity_type}) ${e.controlled_by || ''}
    <button onclick="window.control.toggleControl('${e.id}','${e.controlled_by==='AI'?'HUMAN':'AI'}')">Toggle Human/AI</button></div>`).join('');
}

async function loadDocs() {
  if (!state.selectedCampaign) return;
  const rows = await api(`/api/campaigns/${state.selectedCampaign}/rag/documents`);
  $('docList').innerHTML = rows.map((d) => `<div>${d.filename} - ${d.status} enabled=${d.enabled}
  <button onclick="window.control.docAction('${d.id}','${d.enabled?'disable':'enable'}')">${d.enabled?'Disable':'Enable'}</button>
  <button onclick="window.control.docAction('${d.id}','reindex')">Reindex</button></div>`).join('');
}

async function loadAi() {
  if (!state.selectedCampaign) return;
  const c = await api(`/api/campaigns/${state.selectedCampaign}/ai_config`);
  $('provider').value = c.llm_provider || 'mock';
  $('baseUrl').value = c.llm_base_url || '';
  $('dmModel').value = c.dm_model || '';
  $('npcModel').value = c.npc_model || '';
  $('embedModel').value = c.embedding_model || '';
}

window.control = {
  async pickCampaign(id) { state.selectedCampaign = id; localStorage.setItem('control_campaign_id', id); await refreshAll(); },
  async editCampaign(id) {
    const name = prompt('New campaign name');
    if (!name) return;
    await api(`/api/campaigns/${id}`, { method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
    await loadCampaigns();
  },
  async tombstone(id){ await api(`/api/campaigns/${id}`, {method:'DELETE'}); await loadCampaigns(); },
  async purge(id){ await api(`/api/campaigns/${id}/purge`, {method:'POST'}); await loadCampaigns(); },
  async sessionAction(id, action){ await api(`/api/sessions/${id}/${action}`, {method:'POST'}); await loadSessions(); },
  async toggleControl(id, controlled_by){ await api(`/api/entities/${id}/control`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({controlled_by})}); await loadCharacters(); },
  async docAction(id, action){ await api(`/api/rag/documents/${id}/${action}`, {method:'POST'}); await loadDocs(); },
};

async function refreshAll(){
  showErr('');
  try { await loadCampaigns(); await loadSessions(); await loadCharacters(); await loadDocs(); await loadAi(); }
  catch (e) { showErr(e.message); }
}

window.addEventListener('DOMContentLoaded', async () => {
  tabs();
  $('campaignContext').onchange = async (e) => { state.selectedCampaign = e.target.value; localStorage.setItem('control_campaign_id', state.selectedCampaign); await refreshAll(); };
  $('refreshAll').onclick = refreshAll;
  $('createCampaign').onclick = async () => { try {
      await api('/api/campaigns', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ name:$('campName').value, slug:$('campSlug').value, status:$('campStatus').value, mode:$('campMode').value })});
      await loadCampaigns();
    } catch(e){ showErr(e.message);} };
  $('createSession').onclick = async () => { try { await api(`/api/campaigns/${state.selectedCampaign}/sessions`, {method:'POST'}); await loadSessions(); } catch(e){ showErr(e.message);} };
  $('resumeCampaign').onclick = async () => { try { await api(`/api/campaigns/${state.selectedCampaign}/resume`, {method:'POST'}); await loadSessions(); } catch(e){ showErr(e.message);} };
  $('createCharacter').onclick = async () => { try { const payload = JSON.parse($('characterJson').value); await api(`/api/campaigns/${state.selectedCampaign}/entities`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); await loadCharacters(); } catch(e){ showErr(e.message);} };
  $('generateCharacter').onclick = async () => { try { await api(`/api/campaigns/${state.selectedCampaign}/characters/generate`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({concept:$('charConcept').value})}); await loadCharacters(); } catch(e){ showErr(e.message);} };
  $('uploadRag').onclick = async () => { try { const f = $('ragFile').files[0]; const fd = new FormData(); fd.append('file', f); await api(`/api/campaigns/${state.selectedCampaign}/rag/upload`, {method:'POST',body:fd}); await loadDocs(); } catch(e){ showErr(e.message);} };
  $('testRetrieval').onclick = async () => { try { const res = await api(`/api/campaigns/${state.selectedCampaign}/rag/query`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:$('ragQuery').value, top_k:5})}); $('retrievalOut').textContent = JSON.stringify(res, null, 2);} catch(e){ showErr(e.message);} };
  $('saveAi').onclick = async () => { try { await api(`/api/campaigns/${state.selectedCampaign}/ai_config`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({llm_provider:$('provider').value,llm_base_url:$('baseUrl').value,dm_model:$('dmModel').value,npc_model:$('npcModel').value,embedding_model:$('embedModel').value})}); await loadAi(); } catch(e){ showErr(e.message);} };
  $('listModels').onclick = async () => { try { const res = await api(`/api/ai/models?provider=${encodeURIComponent($('provider').value)}&base_url=${encodeURIComponent($('baseUrl').value)}`); $('aiOut').textContent = JSON.stringify(res, null, 2);} catch(e){ showErr(e.message);} };
  $('testProvider').onclick = async () => { try { const res = await api('/api/ai/test_provider', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:$('provider').value,base_url:$('baseUrl').value,model:$('dmModel').value})}); $('aiOut').textContent = JSON.stringify(res, null, 2);} catch(e){ showErr(e.message);} };
  await refreshAll();
});
