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
            document.querySelectorAll('.tabs button').forEach((x) => x.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach((x) => x.classList.remove('active'));
            b.classList.add('active');
            $(b.dataset.tab).classList.add('active');
        };
    });
}

function statusBadge(status) {
    const s = (status || '').toLowerCase();
    return `<span class="status-badge ${s}">${status}</span>`;
}

function controlBadge(controlledBy) {
    const c = (controlledBy || 'SYSTEM').toLowerCase();
    const label = controlledBy === 'AI_NPC' ? 'AI' : controlledBy || 'SYSTEM';
    return `<span class="control-badge ${c.replace('_', '-')}">${label}</span>`;
}

async function loadCampaigns() {
    state.campaigns = await api('/api/campaigns');
    $('campaignList').innerHTML = state.campaigns.map((c) => `
        <div class="list-item">
            <div class="list-item-info">
                <div class="list-item-name">${escapeHtml(c.name)}</div>
                <div class="list-item-meta">
                    ${escapeHtml(c.slug)} &bull; ${statusBadge(c.status)} &bull;
                    <span class="mode-badge ${c.mode}" style="font-size:10px;padding:2px 6px;">${c.mode}</span>
                </div>
            </div>
            <div class="list-item-actions">
                <button class="btn btn-primary" onclick="window.control.pickCampaign('${c.id}')">Select</button>
                <button class="btn btn-secondary" onclick="window.control.editCampaign('${c.id}')">Edit</button>
                <button class="btn btn-secondary" onclick="window.control.tombstone('${c.id}')">Archive</button>
                <button class="btn btn-danger" onclick="window.control.purge('${c.id}')">Purge</button>
            </div>
        </div>`).join('');

    $('campaignContext').innerHTML = state.campaigns.map((c) =>
        `<option value="${c.id}" ${c.id === state.selectedCampaign ? 'selected' : ''}>${escapeHtml(c.name)}</option>`
    ).join('');

    // Auto-select first campaign if none selected
    if (!state.selectedCampaign && state.campaigns.length > 0) {
        state.selectedCampaign = state.campaigns[0].id;
        localStorage.setItem('control_campaign_id', state.selectedCampaign);
    }
}

async function loadSessions() {
    if (!state.selectedCampaign) {
        $('sessionList').innerHTML = '<div class="list-item-meta">Select a campaign first</div>';
        return;
    }
    const rows = await api(`/api/campaigns/${state.selectedCampaign}/sessions`);
    if (rows.length === 0) {
        $('sessionList').innerHTML = '<div class="list-item-meta">No sessions found. Create one to start playing.</div>';
        return;
    }
    $('sessionList').innerHTML = rows.map((s) => `
        <div class="list-item">
            <div class="list-item-info">
                <div class="list-item-name">Session ${s.id.substring(0, 8)}...</div>
                <div class="list-item-meta">
                    ${statusBadge(s.status)} &bull; Created: ${new Date(s.created_at).toLocaleString()}
                </div>
            </div>
            <div class="list-item-actions">
                <button class="btn btn-secondary" onclick="window.control.sessionAction('${s.id}','pause')">Pause</button>
                <button class="btn btn-primary" onclick="window.control.sessionAction('${s.id}','resume')">Resume</button>
                <button class="btn btn-danger" onclick="window.control.sessionAction('${s.id}','end')">End</button>
            </div>
        </div>`).join('');
}

async function loadCharacters() {
    if (!state.selectedCampaign) {
        $('characterList').innerHTML = '<div class="list-item-meta">Select a campaign first</div>';
        return;
    }
    const rows = await api(`/api/campaigns/${state.selectedCampaign}/entities`);
    const chars = rows.filter(e => ['PC', 'NPC', 'MONSTER'].includes(e.entity_type));
    if (chars.length === 0) {
        $('characterList').innerHTML = '<div class="list-item-meta">No characters found. Create or import one.</div>';
        return;
    }
    $('characterList').innerHTML = chars.map((e) => `
        <div class="list-item">
            <div class="list-item-info">
                <div class="list-item-name">${escapeHtml(e.name)}</div>
                <div class="list-item-meta">
                    <span class="entity-icon ${e.entity_type}" style="display:inline-flex;width:16px;height:16px;font-size:9px;margin-right:4px;">${e.entity_type.charAt(0)}</span>
                    ${e.entity_type} &bull; ${controlBadge(e.controlled_by)}
                    ${e.hp_current != null ? ` &bull; HP: ${e.hp_current}/${e.hp_max}` : ''}
                </div>
            </div>
            <div class="list-item-actions">
                <button class="btn ${e.controlled_by === 'AI' || e.controlled_by === 'AI_NPC' ? 'btn-primary' : 'btn-secondary'}"
                        onclick="window.control.toggleControl('${e.id}','${e.controlled_by === 'AI' || e.controlled_by === 'AI_NPC' ? 'HUMAN' : 'AI'}')">
                    ${e.controlled_by === 'AI' || e.controlled_by === 'AI_NPC' ? 'Set Human' : 'Set AI'}
                </button>
            </div>
        </div>`).join('');
}

async function loadDocs() {
    if (!state.selectedCampaign) {
        $('docList').innerHTML = '<div class="list-item-meta">Select a campaign first</div>';
        return;
    }
    try {
        const rows = await api(`/api/campaigns/${state.selectedCampaign}/rag/documents`);
        if (rows.length === 0) {
            $('docList').innerHTML = '<div class="list-item-meta">No documents uploaded. Upload a file to add to the knowledge base.</div>';
            return;
        }
        $('docList').innerHTML = rows.map((d) => `
            <div class="list-item">
                <div class="list-item-info">
                    <div class="list-item-name">${escapeHtml(d.filename)}</div>
                    <div class="list-item-meta">
                        ${statusBadge(d.status)} &bull;
                        ${d.enabled ? statusBadge('enabled') : statusBadge('disabled')}
                    </div>
                </div>
                <div class="list-item-actions">
                    <button class="btn btn-secondary" onclick="window.control.docAction('${d.id}','${d.enabled ? 'disable' : 'enable'}')">
                        ${d.enabled ? 'Disable' : 'Enable'}
                    </button>
                    <button class="btn btn-secondary" onclick="window.control.docAction('${d.id}','reindex')">Reindex</button>
                </div>
            </div>`).join('');
    } catch (e) {
        $('docList').innerHTML = '<div class="list-item-meta">RAG not available</div>';
    }
}

async function loadAi() {
    if (!state.selectedCampaign) return;
    try {
        const c = await api(`/api/campaigns/${state.selectedCampaign}/ai_config`);
        $('provider').value = c.llm_provider || 'mock';
        $('baseUrl').value = c.llm_base_url || '';
        $('dmModel').value = c.dm_model || '';
        $('npcModel').value = c.npc_model || '';
        $('embedModel').value = c.embedding_model || '';
    } catch (e) {
        // AI config may not exist yet
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;')
              .replace(/'/g, '&#39;');
}

window.control = {
    async pickCampaign(id) {
        state.selectedCampaign = id;
        localStorage.setItem('control_campaign_id', id);
        $('campaignContext').value = id;
        await refreshAll();
    },
    async editCampaign(id) {
        const name = prompt('New campaign name');
        if (!name) return;
        await api(`/api/campaigns/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        await loadCampaigns();
    },
    async tombstone(id) {
        if (!confirm('Archive this campaign? It can be restored later.')) return;
        await api(`/api/campaigns/${id}`, { method: 'DELETE' });
        await loadCampaigns();
    },
    async purge(id) {
        if (!confirm('PERMANENTLY DELETE this campaign? This cannot be undone!')) return;
        await api(`/api/campaigns/${id}/purge`, { method: 'POST' });
        if (state.selectedCampaign === id) {
            state.selectedCampaign = '';
            localStorage.removeItem('control_campaign_id');
        }
        await loadCampaigns();
    },
    async sessionAction(id, action) {
        await api(`/api/sessions/${id}/${action}`, { method: 'POST' });
        await loadSessions();
    },
    async toggleControl(id, controlled_by) {
        await api(`/api/entities/${id}/control`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ controlled_by })
        });
        await loadCharacters();
    },
    async docAction(id, action) {
        await api(`/api/rag/documents/${id}/${action}`, { method: 'POST' });
        await loadDocs();
    },
};

async function refreshAll() {
    showErr('');
    try {
        await loadCampaigns();
        await loadSessions();
        await loadCharacters();
        await loadDocs();
        await loadAi();
    } catch (e) {
        showErr(e.message);
    }
}

window.addEventListener('DOMContentLoaded', async () => {
    tabs();

    $('campaignContext').onchange = async (e) => {
        state.selectedCampaign = e.target.value;
        localStorage.setItem('control_campaign_id', state.selectedCampaign);
        await refreshAll();
    };

    $('refreshAll').onclick = refreshAll;

    $('createCampaign').onclick = async () => {
        try {
            await api('/api/campaigns', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: $('campName').value,
                    slug: $('campSlug').value,
                    status: $('campStatus').value,
                    mode: $('campMode').value
                })
            });
            $('campName').value = '';
            $('campSlug').value = '';
            await loadCampaigns();
        } catch (e) {
            showErr(e.message);
        }
    };

    $('createSession').onclick = async () => {
        try {
            await api(`/api/campaigns/${state.selectedCampaign}/sessions`, { method: 'POST' });
            await loadSessions();
        } catch (e) {
            showErr(e.message);
        }
    };

    $('resumeCampaign').onclick = async () => {
        try {
            await api(`/api/campaigns/${state.selectedCampaign}/resume`, { method: 'POST' });
            await loadSessions();
        } catch (e) {
            showErr(e.message);
        }
    };

    $('createCharacter').onclick = async () => {
        try {
            const payload = JSON.parse($('characterJson').value);
            await api(`/api/campaigns/${state.selectedCampaign}/entities`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            $('characterJson').value = '';
            await loadCharacters();
        } catch (e) {
            showErr(e.message);
        }
    };

    $('generateCharacter').onclick = async () => {
        try {
            await api(`/api/campaigns/${state.selectedCampaign}/characters/generate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ concept: $('charConcept').value })
            });
            $('charConcept').value = '';
            await loadCharacters();
        } catch (e) {
            showErr(e.message);
        }
    };

    $('uploadRag').onclick = async () => {
        try {
            const f = $('ragFile').files[0];
            if (!f) {
                showErr('Please select a file first');
                return;
            }
            const fd = new FormData();
            fd.append('file', f);
            await api(`/api/campaigns/${state.selectedCampaign}/rag/upload`, {
                method: 'POST',
                body: fd
            });
            $('ragFile').value = '';
            await loadDocs();
        } catch (e) {
            showErr(e.message);
        }
    };

    $('testRetrieval').onclick = async () => {
        try {
            const res = await api(`/api/campaigns/${state.selectedCampaign}/rag/query`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: $('ragQuery').value, top_k: 5 })
            });
            $('retrievalOut').textContent = JSON.stringify(res, null, 2);
        } catch (e) {
            showErr(e.message);
        }
    };

    $('saveAi').onclick = async () => {
        try {
            await api(`/api/campaigns/${state.selectedCampaign}/ai_config`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    llm_provider: $('provider').value,
                    llm_base_url: $('baseUrl').value,
                    dm_model: $('dmModel').value,
                    npc_model: $('npcModel').value,
                    embedding_model: $('embedModel').value
                })
            });
            $('aiOut').textContent = 'Settings saved successfully!';
            await loadAi();
        } catch (e) {
            showErr(e.message);
        }
    };

    $('listModels').onclick = async () => {
        try {
            const res = await api(`/api/ai/models?provider=${encodeURIComponent($('provider').value)}&base_url=${encodeURIComponent($('baseUrl').value)}`);
            $('aiOut').textContent = JSON.stringify(res, null, 2);
        } catch (e) {
            showErr(e.message);
        }
    };

    $('testProvider').onclick = async () => {
        try {
            $('aiOut').textContent = 'Testing provider...';
            const res = await api('/api/ai/test_provider', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    provider: $('provider').value,
                    base_url: $('baseUrl').value,
                    model: $('dmModel').value
                })
            });
            $('aiOut').textContent = JSON.stringify(res, null, 2);
        } catch (e) {
            showErr(e.message);
        }
    };

    await refreshAll();
});
