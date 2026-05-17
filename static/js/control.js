const state = {
    campaigns: [],
    selectedCampaign: localStorage.getItem('control_campaign_id') || '',
    selectedSession: localStorage.getItem('control_session_id') || '',
    characters: [],
    sessionCharacters: [],
    viewMode: 'list', // 'list' or 'cards'
    showDeleted: false,
};

const $ = (id) => document.getElementById(id);
const showErr = (msg) => { $('error').textContent = msg || ''; };

// Section toggle for accordion panels
function toggleSection(sectionId) {
    const content = $(sectionId);
    const header = content.previousElementSibling;
    if (content.classList.contains('expanded')) {
        content.classList.remove('expanded');
        header.classList.remove('expanded');
    } else {
        content.classList.add('expanded');
        header.classList.add('expanded');
    }
}

// Make toggleSection globally accessible
window.toggleSection = toggleSection;

// Roll 4d6 drop lowest for a single stat
function roll4d6DropLowest() {
    const rolls = [0, 0, 0, 0].map(() => Math.floor(Math.random() * 6) + 1);
    rolls.sort((a, b) => b - a);
    return rolls[0] + rolls[1] + rolls[2];
}

// Build character object from form
function buildCharacterFromForm() {
    const name = $('charName').value.trim();
    if (!name) {
        throw new Error('Character name is required');
    }

    const skills = $('charSkills').value.split(',').map(s => s.trim()).filter(Boolean);
    const languages = $('charLanguages').value.split(',').map(s => s.trim()).filter(Boolean);

    return {
        name: name,
        entity_type: $('charEntityType').value,
        controlled_by: $('charControlledBy').value,
        hp_max: parseInt($('charHp').value) || 10,
        hp_current: parseInt($('charHp').value) || 10,
        public_sheet: {
            race: $('charRace').value.trim(),
            class: $('charClass').value.trim(),
            level: parseInt($('charLevel').value) || 1,
            background: $('charBackground').value.trim(),
            attributes: {
                strength: parseInt($('charStr').value) || 10,
                dexterity: parseInt($('charDex').value) || 10,
                constitution: parseInt($('charCon').value) || 10,
                intelligence: parseInt($('charInt').value) || 10,
                wisdom: parseInt($('charWis').value) || 10,
                charisma: parseInt($('charCha').value) || 10,
            },
            armor_class: parseInt($('charAc').value) || 10,
            speed: parseInt($('charSpeed').value) || 30,
            initiative_bonus: parseInt($('charInit').value) || 0,
            skills: skills,
            languages: languages,
            abilities: $('charAbilities').value.trim(),
            actions: $('charActions').value.trim(),
            weapons: $('charWeapons').value.trim(),
            armor: $('charArmor').value.trim(),
            equipment: $('charEquipment').value.trim(),
            gold: parseInt($('charGold').value) || 0,
            personality: {
                traits: $('charTraits').value.trim(),
                ideals: $('charIdeals').value.trim(),
                bonds: $('charBonds').value.trim(),
                flaws: $('charFlaws').value.trim(),
                goals: $('charGoals').value.trim(),
            },
            backstory: $('charBackstory').value.trim(),
            allies: $('charAllies').value.trim(),
            enemies: $('charEnemies').value.trim(),
            x: 0,
            y: 0,
        },
        secret_sheet: {
            secrets: $('charSecrets').value.trim(),
            plot_hooks: $('charPlotHooks').value.trim(),
            balance_notes: $('charBalance').value.trim(),
        },
        ac: parseInt($('charAc').value) || 10,
        speed: parseInt($('charSpeed').value) || 30,
    };
}

// Clear character form
function clearCharacterForm() {
    const fields = [
        'charName', 'charRace', 'charClass', 'charBackground',
        'charSkills', 'charLanguages', 'charAbilities', 'charActions',
        'charWeapons', 'charArmor', 'charEquipment',
        'charTraits', 'charIdeals', 'charBonds', 'charFlaws', 'charGoals',
        'charBackstory', 'charAllies', 'charEnemies',
        'charSecrets', 'charPlotHooks', 'charBalance'
    ];
    fields.forEach(id => { if ($(id)) $(id).value = ''; });

    // Reset numbers to defaults
    $('charLevel').value = 1;
    $('charStr').value = 10;
    $('charDex').value = 10;
    $('charCon').value = 10;
    $('charInt').value = 10;
    $('charWis').value = 10;
    $('charCha').value = 10;
    $('charHp').value = 10;
    $('charAc').value = 10;
    $('charSpeed').value = 30;
    $('charInit').value = 0;
    $('charGold').value = 0;

    // Reset selects
    $('charEntityType').value = 'PC';
    $('charControlledBy').value = 'PLAYER';
}

// Populate form from character object (for AI generation)
function populateFormFromCharacter(char) {
    const sheet = char.public_sheet || {};
    const attrs = sheet.attributes || {};
    const personality = sheet.personality || {};
    const secret = char.secret_sheet || {};

    $('charName').value = char.name || '';
    $('charEntityType').value = char.entity_type || 'PC';
    $('charControlledBy').value = char.controlled_by || 'PLAYER';
    $('charRace').value = sheet.race || '';
    $('charClass').value = sheet.class || '';
    $('charLevel').value = sheet.level || 1;
    $('charBackground').value = sheet.background || '';

    $('charStr').value = attrs.strength || 10;
    $('charDex').value = attrs.dexterity || 10;
    $('charCon').value = attrs.constitution || 10;
    $('charInt').value = attrs.intelligence || 10;
    $('charWis').value = attrs.wisdom || 10;
    $('charCha').value = attrs.charisma || 10;

    $('charHp').value = char.hp_max || sheet.hp || 10;
    // AC and speed can be top-level or in public_sheet
    $('charAc').value = char.ac || sheet.armor_class || 10;
    $('charSpeed').value = char.speed || sheet.speed || 30;
    $('charInit').value = sheet.initiative_bonus || 0;

    $('charSkills').value = Array.isArray(sheet.skills) ? sheet.skills.join(', ') : (sheet.skills || '');
    $('charLanguages').value = Array.isArray(sheet.languages) ? sheet.languages.join(', ') : (sheet.languages || '');
    $('charAbilities').value = sheet.abilities || '';
    $('charActions').value = sheet.actions || '';

    $('charWeapons').value = sheet.weapons || '';
    $('charArmor').value = sheet.armor || '';
    $('charEquipment').value = sheet.equipment || '';
    $('charGold').value = sheet.gold || 0;

    $('charTraits').value = personality.traits || '';
    $('charIdeals').value = personality.ideals || '';
    $('charBonds').value = personality.bonds || '';
    $('charFlaws').value = personality.flaws || '';
    $('charGoals').value = personality.goals || '';

    $('charBackstory').value = sheet.backstory || '';
    $('charAllies').value = sheet.allies || '';
    $('charEnemies').value = sheet.enemies || '';

    $('charSecrets').value = secret.secrets || '';
    $('charPlotHooks').value = secret.plot_hooks || '';
    $('charBalance').value = secret.balance_notes || '';

    // Expand the identity section so user sees the result
    const identityContent = $('identity');
    const identityHeader = identityContent.previousElementSibling;
    identityContent.classList.add('expanded');
    identityHeader.classList.add('expanded');
}

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
    const all = await api('/api/campaigns');
    // Hide PURGED always; hide TOMBSTONED unless "Show Deleted" is on.
    state.campaigns = all.filter(c => c.status !== 'PURGED' && (state.showDeleted || c.status !== 'TOMBSTONED'));
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

    // If the previously selected campaign was filtered out, reset selection.
    if (state.selectedCampaign && !state.campaigns.find(c => c.id === state.selectedCampaign)) {
        state.selectedCampaign = '';
        localStorage.removeItem('control_campaign_id');
    }
    // Sync the Save/Load tab's "current campaign" label if the helper's wired.
    window._updateCampaignLabel?.();

    // Auto-select first campaign if none selected
    if (!state.selectedCampaign && state.campaigns.length > 0) {
        state.selectedCampaign = state.campaigns[0].id;
        localStorage.setItem('control_campaign_id', state.selectedCampaign);
    }
}

async function loadCampaignModeBadge() {
    const badge = $('campModeBadge');
    if (!badge) return;
    if (!state.selectedCampaign) { badge.textContent = '--'; badge.className = 'mode-badge'; return; }
    try {
        const res = await api(`/api/campaigns/${state.selectedCampaign}/mode`);
        badge.textContent = res.mode;
        badge.className = `mode-badge ${res.mode}`;
    } catch (e) { /* non-fatal */ }
}

async function loadSessions() {
    if (!state.selectedCampaign) {
        $('sessionList').innerHTML = '<div class="list-item-meta">Select a campaign first</div>';
        state.selectedSession = '';
        return;
    }
    const rows = await api(`/api/campaigns/${state.selectedCampaign}/sessions`);
    if (rows.length === 0) {
        $('sessionList').innerHTML = '<div class="list-item-meta">No sessions found. Create one to start playing.</div>';
        state.selectedSession = '';
        return;
    }

    // Auto-select first ACTIVE session, or first session if none active
    const activeSession = rows.find(s => s.status === 'ACTIVE') || rows[0];
    if (activeSession && (!state.selectedSession || !rows.find(s => s.id === state.selectedSession))) {
        state.selectedSession = activeSession.id;
        localStorage.setItem('control_session_id', state.selectedSession);
    }

    $('sessionList').innerHTML = rows.map((s) => {
        const isSelected = s.id === state.selectedSession;
        return `
        <div class="list-item ${isSelected ? 'selected' : ''}" style="${isSelected ? 'border-color: var(--text-accent);' : ''}">
            <div class="list-item-info">
                <div class="list-item-name">
                    Session ${s.id.substring(0, 8)}...
                    ${isSelected ? '<span style="color: var(--text-accent); font-size: 10px; margin-left: 8px;">(Active Party)</span>' : ''}
                </div>
                <div class="list-item-meta">
                    ${statusBadge(s.status)} &bull; Created: ${new Date(s.created_at).toLocaleString()}
                </div>
            </div>
            <div class="list-item-actions">
                ${!isSelected ? `<button class="btn btn-secondary" onclick="window.control.selectSession('${s.id}')">Select</button>` : ''}
                <button class="btn btn-secondary" onclick="window.control.sessionAction('${s.id}','pause')">Pause</button>
                <button class="btn btn-primary" onclick="window.control.sessionAction('${s.id}','resume')">Resume</button>
                <button class="btn btn-danger" onclick="window.control.sessionAction('${s.id}','end')">End</button>
            </div>
        </div>`;
    }).join('');
}

async function loadCharacters() {
    if (!state.selectedCampaign) {
        $('characterList').innerHTML = '<div class="list-item-meta">Select a campaign first</div>';
        $('characterCards').innerHTML = '';
        return;
    }

    const rows = await api(`/api/campaigns/${state.selectedCampaign}/entities`);
    let chars = rows.filter(e => ['PC', 'NPC', 'MONSTER'].includes(e.entity_type));

    // Filter out deleted unless showing deleted
    if (!state.showDeleted) {
        chars = chars.filter(e => e.status !== 'TOMBSTONED' && e.status !== 'PURGED');
    }

    state.characters = chars;

    if (chars.length === 0) {
        $('characterList').innerHTML = '<div class="list-item-meta">No characters found. Create or import one.</div>';
        $('characterCards').innerHTML = '';
        updateAddCharacterDropdown();
        return;
    }

    // Render list view
    $('characterList').innerHTML = chars.map((e) => renderCharacterListItem(e)).join('');

    // Render card view
    $('characterCards').innerHTML = chars.map((e) => renderCharacterCard(e)).join('');

    // Update the add-to-session dropdown
    updateAddCharacterDropdown();
}

function renderCharacterListItem(e) {
    const isTombstoned = e.status === 'TOMBSTONED';
    const statusClass = isTombstoned ? 'tombstoned' : '';

    return `
        <div class="list-item ${statusClass}">
            <div class="list-item-info" style="display: flex; align-items: center; gap: 12px;">
                ${e.image_url ? `<img src="${e.image_url}" style="width:36px;height:36px;border-radius:50%;object-fit:cover;">` : ''}
                <div>
                    <div class="list-item-name">${escapeHtml(e.name)} ${isTombstoned ? '(Deleted)' : ''}</div>
                    <div class="list-item-meta">
                        <span class="entity-icon ${e.entity_type}" style="display:inline-flex;width:16px;height:16px;font-size:9px;margin-right:4px;">${e.entity_type.charAt(0)}</span>
                        ${e.entity_type} &bull; ${controlBadge(e.controlled_by)}
                        ${e.hp_current != null ? ` &bull; HP: ${e.hp_current}/${e.hp_max}` : ''}
                        ${e.public_sheet?.class ? ` &bull; ${e.public_sheet.class}` : ''}
                    </div>
                </div>
            </div>
            <div class="list-item-actions">
                ${isTombstoned ? `
                    <button class="btn btn-secondary" onclick="window.control.restoreCharacter('${e.id}')">Restore</button>
                ` : `
                    <button class="btn btn-secondary" onclick="window.control.editCharacter('${e.id}')">Edit</button>
                    <button class="btn ${e.controlled_by === 'AI' || e.controlled_by === 'AI_NPC' ? 'btn-primary' : 'btn-secondary'}"
                            onclick="window.control.toggleControl('${e.id}','${e.controlled_by === 'AI' || e.controlled_by === 'AI_NPC' ? 'HUMAN' : 'AI'}')">
                        ${e.controlled_by === 'AI' || e.controlled_by === 'AI_NPC' ? 'Human' : 'AI'}
                    </button>
                    <button class="btn btn-danger" onclick="window.control.deleteCharacter('${e.id}')">Delete</button>
                `}
            </div>
        </div>`;
}

function renderCharacterCard(e) {
    const isTombstoned = e.status === 'TOMBSTONED';
    const sheet = e.public_sheet || {};

    return `
        <div class="character-card ${isTombstoned ? 'tombstoned' : ''}">
            <div class="card-portrait">
                ${e.image_url
                    ? `<img src="${e.image_url}" alt="${escapeHtml(e.name)}">`
                    : `<span class="no-portrait">${e.entity_type.charAt(0)}</span>`}
            </div>
            <div class="card-body">
                <div class="card-name">${escapeHtml(e.name)}</div>
                <div class="card-meta">
                    ${sheet.race || ''} ${sheet.class || ''} ${sheet.level ? `Lv.${sheet.level}` : ''}
                </div>
                <div class="card-stats">
                    ${e.hp_current != null ? `<div class="card-stat">HP: <span class="card-stat-value">${e.hp_current}/${e.hp_max}</span></div>` : ''}
                    ${e.ac != null ? `<div class="card-stat">AC: <span class="card-stat-value">${e.ac}</span></div>` : ''}
                    ${e.speed != null ? `<div class="card-stat">SPD: <span class="card-stat-value">${e.speed}</span></div>` : ''}
                </div>
            </div>
            <div class="card-actions">
                ${isTombstoned ? `
                    <button class="btn btn-secondary" onclick="window.control.restoreCharacter('${e.id}')">Restore</button>
                ` : `
                    <button class="btn btn-secondary" onclick="window.control.editCharacter('${e.id}')">Edit</button>
                    <button class="btn btn-danger" onclick="window.control.deleteCharacter('${e.id}')">Del</button>
                `}
            </div>
        </div>`;
}

function updateAddCharacterDropdown() {
    const select = $('addCharacterSelect');
    if (!select) return;

    // Get characters not in current session
    const sessionEntityIds = state.sessionCharacters.map(sc => sc.entity_id || sc.id);
    const available = state.characters.filter(c =>
        c.status !== 'TOMBSTONED' &&
        !sessionEntityIds.includes(c.id) &&
        !c.is_dead_in_campaign
    );

    select.innerHTML = '<option value="">-- Add Character to Session --</option>' +
        available.map(c => `<option value="${c.id}">${escapeHtml(c.name)} (${c.entity_type})</option>`).join('');
}

async function loadSessionParty() {
    const partyDiv = $('sessionParty');
    if (!partyDiv) return;

    if (!state.selectedSession) {
        partyDiv.innerHTML = '<div class="list-item-meta">No active session selected</div>';
        return;
    }

    try {
        const chars = await api(`/api/sessions/${state.selectedSession}/characters`);
        state.sessionCharacters = chars;

        if (chars.length === 0) {
            partyDiv.innerHTML = '<div class="list-item-meta">No characters in this session. Add characters below.</div>';
            updateAddCharacterDropdown();
            return;
        }

        partyDiv.innerHTML = chars.map(c => renderPartyMember(c)).join('');
        updateAddCharacterDropdown();
    } catch (e) {
        partyDiv.innerHTML = '<div class="list-item-meta">Could not load session party</div>';
    }
}

function renderPartyMember(c) {
    const isDead = c.session_status === 'DEAD';
    const hpPercent = c.hp_max > 0 ? Math.round((c.hp_current / c.hp_max) * 100) : 0;
    const hpClass = hpPercent <= 25 ? 'critical' : hpPercent <= 50 ? 'low' : '';

    return `
        <div class="party-member ${isDead ? 'dead' : ''}">
            <div class="party-avatar">
                ${c.image_url
                    ? `<img src="${c.image_url}" alt="${escapeHtml(c.name)}">`
                    : `<span class="avatar-placeholder">${c.name.charAt(0)}</span>`}
            </div>
            <div class="party-info">
                <div class="party-name">${escapeHtml(c.name)} ${isDead ? '(Dead)' : ''}</div>
                <div class="party-stats">
                    HP: ${c.hp_current}/${c.hp_max}
                    <span class="hp-bar"><span class="hp-bar-fill ${hpClass}" style="width:${hpPercent}%"></span></span>
                    &bull; AC: ${c.ac || '?'}
                </div>
            </div>
            <div class="party-actions">
                ${isDead ? `
                    <button class="btn btn-primary" onclick="window.control.reviveCharacter('${c.id}')">Revive</button>
                ` : `
                    <button class="btn btn-danger" onclick="window.control.markDead('${c.id}')">Mark Dead</button>
                `}
                <button class="btn btn-secondary" onclick="window.control.removeFromSession('${c.id}')">Remove</button>
            </div>
        </div>`;
}

// Modal functions
function openEditModal(entity) {
    const modal = $('editCharacterModal');
    $('editCharId').value = entity.id;
    $('editCharName').value = entity.name || '';
    $('editCharEntityType').value = entity.entity_type || 'PC';
    $('editCharControlledBy').value = entity.controlled_by || 'PLAYER';
    $('editCharHpCurrent').value = entity.hp_current || 0;
    $('editCharHpMax').value = entity.hp_max || 0;
    $('editCharAc').value = entity.ac || 10;
    $('editCharSpeed').value = entity.speed || 30;
    $('editCharPublicSheet').value = JSON.stringify(entity.public_sheet || {}, null, 2);

    // Image preview
    const preview = $('editCharImagePreview');
    if (entity.image_url) {
        preview.innerHTML = `<img src="${entity.image_url}" style="max-width:100px;max-height:100px;border-radius:8px;">`;
    } else {
        preview.innerHTML = '<span style="color:var(--text-secondary);font-size:12px;">No image</span>';
    }

    modal.style.display = 'flex';
}

function closeEditModal() {
    $('editCharacterModal').style.display = 'none';
}
window.closeEditModal = closeEditModal;

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
        // Image-gen panel: read out of settings JSONB (set by saveImgSettings)
        const s = c.settings || {};
        const ig = s.image_gen || {};
        if ($('imgProvider')) $('imgProvider').value = ig.provider || 'openrouter';
        if ($('imgModel')) $('imgModel').value = ig.model || '';
        if ($('imgHostModel')) $('imgHostModel').value = ig.host_model || '';
        // Never display saved keys — placeholder hint only.
        const hasKey = !!((s.api_keys || {})[c.llm_provider]);
        const ph = hasKey ? 'leave blank to keep saved key' : 'no key saved';
        if ($('apiKey')) $('apiKey').placeholder = ph;
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
        window._updateCampaignLabel?.();
    },

    // Session Intel patch actions (called from inline onclicks in the
    // patch-card template above).
    async approvePatch(pid) {
        try {
            await api(`/api/patches/${pid}/approve`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
            });
            // Reload the patch list + continuity panels.
            if (window._reloadIntel) window._reloadIntel();
        } catch (e) { showErr(e.message); }
    },
    async rejectPatch(pid) {
        const notes = prompt('Reason for rejection (optional):') || '';
        try {
            await api(`/api/patches/${pid}/reject`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ notes }),
            });
            if (window._reloadIntel) window._reloadIntel();
        } catch (e) { showErr(e.message); }
    },
    editPatch(pid, patchJSON, visibility, summary) {
        // Open the modal pre-filled. patchJSON is already parsed by the
        // template (it came in via JSON.stringify in the data attribute).
        $('patchEditId').value = pid;
        $('patchEditSummary').value = summary || '';
        $('patchEditVisibility').value = visibility || 'party';
        $('patchEditPatch').value = JSON.stringify(patchJSON || {}, null, 2);
        $('patchEditModal').style.display = 'flex';
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
        await loadSessionParty();
    },
    async selectSession(id) {
        state.selectedSession = id;
        localStorage.setItem('control_session_id', id);
        await loadSessions();
        await loadSessionParty();
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

    // Character Management
    async editCharacter(id) {
        const entity = state.characters.find(c => c.id === id);
        if (entity) {
            openEditModal(entity);
        }
    },
    async deleteCharacter(id) {
        const entity = state.characters.find(c => c.id === id);
        if (!confirm(`Delete ${entity?.name || 'this character'}? It can be restored later.`)) return;
        try {
            await api(`/api/entities/${id}`, { method: 'DELETE' });
            await loadCharacters();
            await loadSessionParty();
        } catch (e) {
            showErr(e.message);
        }
    },
    async restoreCharacter(id) {
        try {
            await api(`/api/entities/${id}/restore`, { method: 'POST' });
            await loadCharacters();
        } catch (e) {
            showErr(e.message);
        }
    },

    // Session Party Management
    async addToSession(entityId) {
        if (!state.selectedSession) {
            showErr('No session selected');
            return;
        }
        if (!entityId) {
            showErr('Select a character to add');
            return;
        }
        try {
            await api(`/api/sessions/${state.selectedSession}/characters`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ entity_id: entityId })
            });
            await loadSessionParty();
            showErr('');
        } catch (e) {
            showErr(e.message);
        }
    },
    async removeFromSession(entityId) {
        if (!confirm('Remove this character from the session?')) return;
        try {
            await api(`/api/sessions/${state.selectedSession}/characters/${entityId}`, {
                method: 'DELETE'
            });
            await loadSessionParty();
        } catch (e) {
            showErr(e.message);
        }
    },
    async markDead(entityId) {
        if (!confirm('Mark this character as dead? They can be revived later.')) return;
        try {
            await api(`/api/sessions/${state.selectedSession}/characters/${entityId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    status: 'DEAD',
                    death_type: 'COMBAT',
                    death_details: { marked_at: new Date().toISOString() }
                })
            });
            await loadSessionParty();
        } catch (e) {
            showErr(e.message);
        }
    },
    async reviveCharacter(entityId) {
        const method = prompt('Revive method? (SPELL, DIVINE_INTERVENTION, STORY)', 'STORY');
        if (!method) return;
        try {
            await api(`/api/sessions/${state.selectedSession}/characters/${entityId}/revive`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    method: method,
                    restore_hp: 1,
                    revive_details: { revived_at: new Date().toISOString() }
                })
            });
            await loadSessionParty();
            await loadCharacters();
        } catch (e) {
            showErr(e.message);
        }
    },

    // Image upload
    async uploadCharacterImage() {
        const entityId = $('editCharId').value;
        const fileInput = $('editCharImage');
        if (!fileInput.files[0]) {
            showErr('Select an image file');
            return;
        }
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        try {
            const result = await fetch(`/api/entities/${entityId}/image`, {
                method: 'POST',
                body: formData
            }).then(r => r.json());
            if (result.error) throw new Error(result.error);
            $('editCharImagePreview').innerHTML = `<img src="${result.image_url}" style="max-width:100px;max-height:100px;border-radius:8px;">`;
            await loadCharacters();
            showErr('');
        } catch (e) {
            showErr(e.message);
        }
    },
    async removeCharacterImage() {
        const entityId = $('editCharId').value;
        try {
            await api(`/api/entities/${entityId}/image`, { method: 'DELETE' });
            $('editCharImagePreview').innerHTML = '<span style="color:var(--text-secondary);font-size:12px;">No image</span>';
            await loadCharacters();
        } catch (e) {
            showErr(e.message);
        }
    },
    async saveCharacterEdit() {
        const entityId = $('editCharId').value;
        let publicSheet;
        try {
            publicSheet = JSON.parse($('editCharPublicSheet').value || '{}');
        } catch (e) {
            showErr('Invalid JSON in public sheet');
            return;
        }
        try {
            await api(`/api/entities/${entityId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: $('editCharName').value,
                    entity_type: $('editCharEntityType').value,
                    controlled_by: $('editCharControlledBy').value,
                    hp_current: parseInt($('editCharHpCurrent').value) || 0,
                    hp_max: parseInt($('editCharHpMax').value) || 0,
                    ac: parseInt($('editCharAc').value) || 10,
                    speed: parseInt($('editCharSpeed').value) || 30,
                    public_sheet: publicSheet,
                })
            });
            closeEditModal();
            await loadCharacters();
            await loadSessionParty();
            showErr('');
        } catch (e) {
            showErr(e.message);
        }
    },

    // Session Archives
    currentArchiveId: null,

    async viewArchive(id) {
        try {
            const archive = await api(`/api/session_archives/${id}`);
            this.currentArchiveId = id;

            // Update modal header
            const metaEl = $('historyMeta');
            if (metaEl) {
                metaEl.innerHTML = `
                    <div class="history-info">
                        <strong>${archive.session_name || 'Session ' + (archive.session_number || archive.original_session_id?.substring(0, 8))}</strong>
                        <span class="history-date">
                            ${archive.started_at ? new Date(archive.started_at).toLocaleDateString() : 'Unknown start'}
                            - ${archive.ended_at ? new Date(archive.ended_at).toLocaleDateString() : 'Ongoing'}
                        </span>
                    </div>
                    ${archive.session_summary ? `<div class="history-summary">${escapeHtml(archive.session_summary)}</div>` : ''}
                `;
            }

            // Render story state snapshot
            const storyEl = $('historyStoryState');
            if (storyEl && archive.final_story_state) {
                const ss = archive.final_story_state;
                storyEl.innerHTML = `
                    <div class="story-snapshot">
                        ${ss.current_location ? `<div><strong>Location:</strong> ${escapeHtml(ss.current_location)}</div>` : ''}
                        ${ss.game_time ? `<div><strong>Time:</strong> ${escapeHtml(ss.game_time)}</div>` : ''}
                        ${ss.dm_notes ? `<div class="dm-notes"><strong>DM Notes:</strong> ${escapeHtml(ss.dm_notes)}</div>` : ''}
                    </div>
                `;
            }

            // Render chat history
            const chatEl = $('historyChatLog');
            if (chatEl && archive.chat_history) {
                const messages = archive.chat_history;
                if (messages.length === 0) {
                    chatEl.innerHTML = '<div class="list-item-meta">No messages in this session</div>';
                } else {
                    chatEl.innerHTML = messages.map(msg => {
                        const timestamp = msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString() : '--:--';
                        const type = (msg.event_type || 'system').toLowerCase();
                        const payload = msg.payload || {};
                        let content = '';

                        if (type === 'chat' || type === 'dialogue') {
                            const speaker = payload.speaker || 'Unknown';
                            content = `<span class="chat-speaker">${escapeHtml(speaker)}:</span> ${escapeHtml(payload.message || payload.dialogue || '')}`;
                        } else if (type === 'narration') {
                            content = `<em>${escapeHtml(payload.narration || payload.message || '')}</em>`;
                        } else if (type === 'action') {
                            content = `<strong>${escapeHtml(payload.action_type || 'Action')}</strong>`;
                        } else {
                            content = escapeHtml(payload.message || JSON.stringify(payload).substring(0, 100));
                        }

                        return `<div class="chat-message ${type}"><span class="chat-time">${timestamp}</span> ${content}</div>`;
                    }).join('');
                }
            }

            // Show modal
            const modal = $('sessionHistoryModal');
            if (modal) modal.style.display = 'flex';
        } catch (e) {
            showErr('Failed to load archive: ' + e.message);
        }
    },

    closeHistoryModal() {
        const modal = $('sessionHistoryModal');
        if (modal) modal.style.display = 'none';
        this.currentArchiveId = null;
    },

    async deleteArchive(id) {
        const archiveId = id || this.currentArchiveId;
        if (!archiveId) return;
        if (!confirm('Permanently delete this archived session? This cannot be undone.')) return;

        try {
            await api(`/api/session_archives/${archiveId}`, { method: 'DELETE' });
            this.closeHistoryModal();
            await loadArchives();
            showErr('');
        } catch (e) {
            showErr('Failed to delete archive: ' + e.message);
        }
    },
};

// Session Archives
async function loadArchives() {
    if (!state.selectedCampaign) {
        const el = $('sessionArchives');
        if (el) el.innerHTML = '<div class="list-item-meta">Select a campaign to see archived sessions</div>';
        return;
    }

    try {
        const archives = await api(`/api/campaigns/${state.selectedCampaign}/session_archives`);
        const el = $('sessionArchives');
        if (!el) return;

        if (archives.length === 0) {
            el.innerHTML = '<div class="list-item-meta">No archived sessions yet</div>';
            return;
        }

        el.innerHTML = archives.map(a => `
            <div class="list-item">
                <div class="list-item-info">
                    <div class="list-item-name">
                        ${a.session_name || 'Session ' + (a.session_number || a.original_session_id.substring(0, 8))}
                    </div>
                    <div class="list-item-meta">
                        ${statusBadge(a.archive_reason)} &bull;
                        Archived: ${new Date(a.archived_at).toLocaleString()}
                        ${a.chat_count ? `&bull; ${a.chat_count} messages` : ''}
                    </div>
                </div>
                <div class="list-item-actions">
                    <button class="btn btn-secondary" onclick="window.control.viewArchive('${a.id}')">View History</button>
                    <button class="btn btn-danger" onclick="window.control.deleteArchive('${a.id}')">Delete</button>
                </div>
            </div>
        `).join('');
    } catch (e) {
        console.error('Failed to load archives:', e);
    }
}

async function refreshAll() {
    showErr('');
    try {
        await loadCampaigns();
        await loadCampaignModeBadge();
        await loadSessions();
        await loadArchives();
        await loadCharacters();
        await loadSessionParty();
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

    const setMode = async (newMode) => {
        if (!state.selectedCampaign) { showErr('Select a campaign first'); return; }
        try {
            await api(`/api/campaigns/${state.selectedCampaign}/mode`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode: newMode }),
            });
            await loadCampaignModeBadge();
            await loadCampaigns();
        } catch (e) {
            showErr(e.message);
        }
    };
    $('btnEnterCombat').onclick = () => setMode('COMBAT');
    $('btnExitCombat').onclick = () => setMode('EXPLORATION');

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
            const concept = $('charConcept').value.trim();
            if (!concept) {
                showErr('Please enter a character concept');
                return;
            }
            showErr('');
            $('generateCharacter').disabled = true;
            $('generateCharacter').textContent = 'Generating...';

            const result = await api(`/api/campaigns/${state.selectedCampaign}/characters/generate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ concept: concept, populate_form: true })
            });

            // Populate form with generated character
            if (result.character) {
                populateFormFromCharacter(result.character);
                $('charConcept').value = '';
                showErr('');
            }
            await loadCharacters();
        } catch (e) {
            showErr(e.message);
        } finally {
            $('generateCharacter').disabled = false;
            $('generateCharacter').textContent = 'AI Generate';
        }
    };

    // Character builder form handlers
    $('createCharacterForm').onclick = async () => {
        try {
            const payload = buildCharacterFromForm();
            await api(`/api/campaigns/${state.selectedCampaign}/entities`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            clearCharacterForm();
            await loadCharacters();
            showErr('');
        } catch (e) {
            showErr(e.message);
        }
    };

    $('randomizeStats').onclick = () => {
        $('charStr').value = roll4d6DropLowest();
        $('charDex').value = roll4d6DropLowest();
        $('charCon').value = roll4d6DropLowest();
        $('charInt').value = roll4d6DropLowest();
        $('charWis').value = roll4d6DropLowest();
        $('charCha').value = roll4d6DropLowest();

        // Calculate HP based on constitution
        const conMod = Math.floor((parseInt($('charCon').value) - 10) / 2);
        const level = parseInt($('charLevel').value) || 1;
        // Assume d8 hit die as default
        const baseHp = 8 + conMod + ((level - 1) * (5 + conMod));
        $('charHp').value = Math.max(1, baseHp);

        // Calculate initiative from dexterity
        const dexMod = Math.floor((parseInt($('charDex').value) - 10) / 2);
        $('charInit').value = dexMod;

        // Expand attributes section to show results
        const attrsContent = $('attributes');
        const attrsHeader = attrsContent.previousElementSibling;
        attrsContent.classList.add('expanded');
        attrsHeader.classList.add('expanded');
    };

    $('clearCharacterForm').onclick = () => {
        clearCharacterForm();
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
            const body = {
                llm_provider: $('provider').value,
                llm_base_url: $('baseUrl').value,
                dm_model: $('dmModel').value,
                npc_model: $('npcModel').value,
                embedding_model: $('embedModel').value,
            };
            // Only send api_key if user typed one — empty means "keep existing".
            const k = $('apiKey').value.trim();
            if (k) body.api_key = k;
            await api(`/api/campaigns/${state.selectedCampaign}/ai_config`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            $('apiKey').value = ''; // clear field so user knows it's saved
            $('aiOut').textContent = 'Settings saved.';
            await loadAi();
        } catch (e) {
            showErr(e.message);
        }
    };

    if ($('testImgGen')) {
        $('testImgGen').onclick = async () => {
            if (!state.selectedCampaign) { showErr('Select a campaign first'); return; }
            const out = $('imgOut');
            const img = $('imgPreview');
            out.textContent = 'Calling provider…';
            img.style.display = 'none';
            try {
                const res = await api(`/api/campaigns/${state.selectedCampaign}/test_image_gen`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({}),
                });
                out.textContent = `OK — ${res.provider} / ${res.model}\n${res.image_url_preview}`;
                if (res.image_url) {
                    img.src = res.image_url;
                    img.style.display = 'block';
                }
            } catch (e) {
                out.textContent = `Error: ${e.message}`;
                img.style.display = 'none';
            }
        };
    }

    if ($('saveImgSettings')) {
        $('saveImgSettings').onclick = async () => {
            try {
                const settings = {
                    image_gen: {
                        provider: $('imgProvider').value,
                        model: $('imgModel').value || 'google/gemini-2.5-flash-image',
                        host_model: $('imgHostModel').value || 'openai/gpt-4o-mini',
                    },
                };
                const k = $('imgApiKey').value.trim();
                if (k) settings.api_keys = { [`image_${$('imgProvider').value}`]: k };
                await api(`/api/campaigns/${state.selectedCampaign}/ai_config`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        llm_provider: $('provider').value || 'mock',
                        settings,
                    }),
                });
                $('imgApiKey').value = '';
                $('imgOut').textContent = 'Image settings saved.';
                await loadAi();
            } catch (e) {
                showErr(e.message);
            }
        };
    }

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

    // ===== API Keys tab =====
    // Provider key fields are <input type=password>. Server-side, values
    // are encrypted at rest with a vault key in .local-run/vault.key.
    // On GET, the server returns "********" for any present key — we use
    // that to set placeholders so the user sees status without value leak.

    const KEY_PROVIDERS = ["openrouter", "openai", "anthropic", "deepseek"];

    async function loadApiKeys() {
        if (!$('key_openrouter')) return; // tab not present
        try {
            const gs = await api('/api/global_settings');
            const keys = gs?.api_keys || {};
            for (const p of KEY_PROVIDERS) {
                const present = !!keys[p];
                const input = $('key_' + p);
                if (input) {
                    input.value = '';
                    input.placeholder = present ? 'saved (********), leave blank to keep' : 'paste your key';
                }
                const status = $('status_' + p);
                if (status) {
                    status.textContent = present ? 'saved' : 'no key saved';
                    status.style.color = present ? 'var(--text-accent)' : 'var(--text-secondary)';
                }
            }
        } catch (e) { /* non-fatal — tab might be hidden, ignore */ }
    }

    if ($('saveApiKeys')) {
        $('saveApiKeys').onclick = async () => {
            const payload = {};
            let touched = 0;
            for (const p of KEY_PROVIDERS) {
                const v = $('key_' + p).value;
                if (v !== '') {
                    payload[p] = v;
                    touched++;
                }
            }
            if (touched === 0) {
                $('apiKeysStatus').textContent = 'Nothing changed.';
                return;
            }
            $('apiKeysStatus').textContent = 'Saving…';
            try {
                await api('/api/global_settings/api_keys', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                $('apiKeysStatus').textContent = `Saved ${touched} key(s). Cleartext was encrypted before storage.`;
                await loadApiKeys();
            } catch (e) {
                $('apiKeysStatus').textContent = 'Error: ' + e.message;
            }
        };
    }

    // Refresh status whenever the user clicks the API Keys tab.
    document.querySelectorAll('.tab').forEach(b => {
        if (b.dataset.tab === 'keys') {
            b.addEventListener('click', loadApiKeys);
        }
    });
    // Initial load (in case the user lands on the tab directly).
    loadApiKeys();

    // ===== Session Intel tab =====
    // Browse pending patches from state.proposed_story_patches, approve/edit/reject,
    // view visibility-scoped recaps, surface continuity (open threads / promises /
    // contradictions). The API does the heavy lifting; this is just a thin shell.

    // event_type → CSS group + display label
    const PATCH_KIND_CLASS = {
        location_changed: 'location', scene_started: 'scene', scene_ended: 'scene',
        npc_introduced: 'npc', npc_updated: 'npc', npc_attitude_changed: 'npc',
        quest_introduced: 'quest', quest_updated: 'quest',
        promise_made: 'thread', threat_created: 'thread', consequence_created: 'thread', unresolved_thread: 'thread',
        secret_revealed: 'secret',
        retcon_or_contradiction: 'retcon',
        loot_gained: 'loot', item_used: 'loot',
    };
    const PATCH_VIS_LABEL = { public: 'PUBLIC', party: 'PARTY', dm_only: 'DM ONLY', principal_scoped: 'PRINCIPAL' };

    let intelCurrentSessionId = null;

    async function loadIntelSessions() {
        const sel = $('intelSession');
        if (!sel || !state.selectedCampaign) return;
        try {
            const sessions = await api(`/api/campaigns/${state.selectedCampaign}/sessions`);
            sel.innerHTML = sessions.length === 0
                ? '<option value="">no sessions</option>'
                : sessions.map(s => `<option value="${s.id}">${s.id.slice(0,8)} — ${s.status} — ${s.started_at?.slice(0,16) || ''}</option>`).join('');
            // Auto-pick the first ACTIVE session
            const active = sessions.find(s => s.status === 'ACTIVE') || sessions[0];
            if (active) {
                sel.value = active.id;
                intelCurrentSessionId = active.id;
            }
        } catch (e) { showErr(e.message); }
    }

    function escapePre(s) { return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

    async function loadPendingPatches() {
        if (!state.selectedCampaign) return;
        const params = new URLSearchParams({ status: 'PENDING' });
        if (intelCurrentSessionId) params.set('session_id', intelCurrentSessionId);
        try {
            const patches = await api(`/api/campaigns/${state.selectedCampaign}/patches?${params}`);
            $('intelPendingCount').textContent = `${patches.length} pending`;
            const listEl = $('intelPatchList');
            if (patches.length === 0) {
                listEl.innerHTML = '<div class="list-item-meta">No pending patches. Run the extractor or wait for play activity.</div>';
                return;
            }
            listEl.innerHTML = patches.map(p => {
                const kindClass = PATCH_KIND_CLASS[p.event_type] || 'other';
                const conf = Math.round((p.confidence || 0) * 100);
                const evidence = (p.evidence || []).filter(e => e.quote).map(e =>
                    `<div class="patch-evidence">"${escapeHtml(e.quote)}"</div>`
                ).join('');
                const entityList = Array.isArray(p.entities) && p.entities.length
                    ? `<div class="patch-evidence">entities: ${p.entities.map(escapeHtml).join(', ')}</div>` : '';
                return `
                <div class="patch-card kind-${kindClass}" data-pid="${p.id}">
                    <div class="patch-head">
                        <span class="patch-type">${p.event_type}</span>
                        <span class="patch-vis">${PATCH_VIS_LABEL[p.visibility] || p.visibility}</span>
                    </div>
                    <div class="patch-summary">${escapeHtml(p.summary)}</div>
                    ${entityList}
                    ${evidence}
                    <div class="help-text">
                        confidence: ${conf}%
                        <span class="patch-conf"><span style="width:${conf}%"></span></span>
                    </div>
                    <div class="patch-actions">
                        <button class="btn btn-primary btn-sm" onclick="window.control.approvePatch('${p.id}')">Approve & Apply</button>
                        <button class="btn btn-secondary btn-sm" onclick="window.control.editPatch('${p.id}', ${JSON.stringify(p.patch || {}).replace(/"/g, '&quot;')}, '${p.visibility}', '${escapeHtml(p.summary).replace(/'/g, '&#39;')}')">Edit</button>
                        <button class="btn btn-danger btn-sm" onclick="window.control.rejectPatch('${p.id}')">Reject</button>
                    </div>
                </div>`;
            }).join('');
        } catch (e) {
            showErr(e.message);
        }
    }

    async function loadContinuity() {
        if (!state.selectedCampaign) return;
        try {
            const threads = await api(`/api/campaigns/${state.selectedCampaign}/open_threads`);
            const promises = await api(`/api/campaigns/${state.selectedCampaign}/unresolved_promises`);
            const patches = await api(`/api/campaigns/${state.selectedCampaign}/patches?status=*&event_type=retcon_or_contradiction`);

            const fmt = (rows, emptyText) => rows.length === 0
                ? `<div class="list-item-meta">${emptyText}</div>`
                : rows.map(r => `<div class="list-item"><div class="list-item-info"><div class="list-item-name">${escapeHtml(r.summary)}</div><div class="list-item-meta">${r.event_type || ''} · ${(r.created_at || '').slice(0,16)}</div></div></div>`).join('');

            $('intelOpenThreads').innerHTML = fmt(threads, 'No open threads.');
            $('intelPromises').innerHTML = fmt(promises, 'No outstanding promises.');
            $('intelContradictions').innerHTML = fmt(patches, 'No contradictions flagged.');
        } catch (e) { /* non-fatal */ }
    }

    async function loadRecap(visibility) {
        if (!intelCurrentSessionId) {
            $('intelRecap').textContent = 'Select a session first.'; return;
        }
        $('intelRecap').textContent = 'Loading recap…';
        try {
            const res = await api(`/api/sessions/${intelCurrentSessionId}/recap?visibility=${visibility}`);
            $('intelRecap').textContent = res.recap || '(empty)';
        } catch (e) {
            $('intelRecap').textContent = 'Error: ' + e.message;
        }
    }

    if ($('intelSession')) {
        $('intelSession').onchange = (e) => {
            intelCurrentSessionId = e.target.value;
            loadPendingPatches();
        };
    }
    if ($('btnIntelRefresh')) $('btnIntelRefresh').onclick = () => {
        loadIntelSessions().then(() => { loadPendingPatches(); loadContinuity(); });
    };
    if ($('btnIntelExtract')) $('btnIntelExtract').onclick = async () => {
        if (!intelCurrentSessionId) { $('intelOut').textContent = 'Pick a session first.'; return; }
        $('intelOut').textContent = 'Running deterministic extractor…';
        try {
            const res = await api(`/api/sessions/${intelCurrentSessionId}/intel/extract`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ deterministic_only: true }),
            });
            $('intelOut').textContent = `Extracted ${res.proposed_count} candidate event(s). Skipped: ${(res.skipped || []).join(', ') || 'none'}`;
            await loadPendingPatches();
        } catch (e) { $('intelOut').textContent = 'Error: ' + e.message; }
    };
    if ($('btnIntelExtractLLM')) $('btnIntelExtractLLM').onclick = async () => {
        if (!intelCurrentSessionId) { $('intelOut').textContent = 'Pick a session first.'; return; }
        $('intelOut').textContent = 'Running extractor (LLM path active — needs an API key)…';
        try {
            const res = await api(`/api/sessions/${intelCurrentSessionId}/intel/extract`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ deterministic_only: false }),
            });
            $('intelOut').textContent = `Extracted ${res.proposed_count} candidate event(s). Skipped: ${(res.skipped || []).join(', ') || 'none'}`;
            await loadPendingPatches();
        } catch (e) { $('intelOut').textContent = 'Error: ' + e.message; }
    };
    if ($('btnIntelPacket')) $('btnIntelPacket').onclick = async () => {
        if (!intelCurrentSessionId) { $('intelOut').textContent = 'Pick a session first.'; return; }
        $('intelOut').textContent = 'Generating DM packet…';
        try {
            const res = await api(`/api/sessions/${intelCurrentSessionId}/dm_packet`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ deterministic_only: true }),
            });
            $('intelOut').textContent = JSON.stringify({
                generated_at: res.generated_at,
                pending: res.pending_patches.length,
                open_threads: res.open_threads.length,
                contradictions: res.contradictions.length,
            }, null, 2);
            $('intelRecap').textContent = `=== DM RECAP ===\n${res.dm_recap}\n\n=== PARTY RECAP ===\n${res.party_recap}`;
            await loadPendingPatches();
            await loadContinuity();
        } catch (e) { $('intelOut').textContent = 'Error: ' + e.message; }
    };
    if ($('btnRecapDm'))     $('btnRecapDm').onclick     = () => loadRecap('dm');
    if ($('btnRecapParty'))  $('btnRecapParty').onclick  = () => loadRecap('party');
    if ($('btnRecapPublic')) $('btnRecapPublic').onclick = () => loadRecap('public');

    // Patch modal actions
    if ($('patchEditSave')) $('patchEditSave').onclick = async () => {
        const pid = $('patchEditId').value;
        if (!pid) return;
        let patchJSON;
        try {
            patchJSON = JSON.parse($('patchEditPatch').value || '{}');
        } catch (e) {
            $('intelOut').textContent = 'Patch payload must be valid JSON: ' + e.message;
            return;
        }
        try {
            await api(`/api/patches/${pid}/edit`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    summary: $('patchEditSummary').value,
                    visibility: $('patchEditVisibility').value,
                    patch: patchJSON,
                }),
            });
            $('patchEditModal').style.display = 'none';
            await loadPendingPatches();
            $('intelOut').textContent = 'Patch edited (status EDITED — click Approve & Apply to commit).';
        } catch (e) { $('intelOut').textContent = 'Error: ' + e.message; }
    };
    if ($('patchEditApply')) $('patchEditApply').onclick = async () => {
        await $('patchEditSave').click();
        const pid = $('patchEditId').value;
        if (!pid) return;
        try {
            await api(`/api/patches/${pid}/approve`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}),
            });
            $('intelOut').textContent = 'Edited + applied.';
            await loadPendingPatches();
            await loadContinuity();
        } catch (e) { $('intelOut').textContent = 'Error: ' + e.message; }
    };

    // When the user clicks the Session Intel tab, refresh everything.
    document.querySelectorAll('.tab').forEach(b => {
        if (b.dataset.tab === 'intel') {
            b.addEventListener('click', () => {
                loadIntelSessions().then(() => { loadPendingPatches(); loadContinuity(); });
            });
        }
    });
    // Expose a thin reload helper for patch action handlers on window.control.
    window._reloadIntel = () => { loadPendingPatches(); loadContinuity(); };

    // ===== Save / Load tab =====
    // Files live entirely on the user's filesystem; the server only encrypts/
    // decrypts on demand. Passphrase is prompted in-page and never stored.

    async function downloadEncrypted(endpoint, body, filename) {
        const r = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!r.ok) {
            let msg;
            try { msg = (await r.json()).error; } catch { msg = r.statusText; }
            throw new Error(msg || 'export failed');
        }
        const blob = await r.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
    }

    if ($('btnExportProgram')) {
        $('btnExportProgram').onclick = async () => {
            const pw = prompt('Choose a passphrase for this program save:');
            if (!pw) return;
            const confirm = prompt('Confirm the passphrase:');
            if (confirm !== pw) { $('programSaveOut').textContent = 'Passphrases did not match.'; return; }
            $('programSaveOut').textContent = 'Generating encrypted program save…';
            try {
                await downloadEncrypted('/api/saves/program/export', { passphrase: pw }, 'program.ttdm');
                $('programSaveOut').textContent = 'Downloaded program.ttdm. Store it somewhere safe — anyone with the file and passphrase can read your API keys.';
            } catch (e) { $('programSaveOut').textContent = `Error: ${e.message}`; }
        };
    }

    if ($('btnImportProgram')) {
        $('btnImportProgram').onclick = async () => {
            const f = $('importProgramFile').files[0];
            if (!f) { $('programSaveOut').textContent = 'Pick a .ttdm file first.'; return; }
            const pw = prompt('Passphrase for the program save:');
            if (!pw) return;
            $('programSaveOut').textContent = 'Decrypting and importing…';
            const fd = new FormData();
            fd.append('file', f);
            fd.append('passphrase', pw);
            try {
                const r = await fetch('/api/saves/program/import', { method: 'POST', body: fd });
                const res = await r.json();
                if (!r.ok) throw new Error(res.error || 'import failed');
                $('programSaveOut').textContent =
                    `Imported ${res.settings_imported} setting(s) and ${res.principals_imported} principal(s).`;
                await refreshAll();
            } catch (e) { $('programSaveOut').textContent = `Error: ${e.message}`; }
        };
    }

    if ($('btnExportGame')) {
        $('btnExportGame').onclick = async () => {
            if (!state.selectedCampaign) { $('gameSaveOut').textContent = 'Select a campaign first.'; return; }
            const pw = prompt('Choose a passphrase for this game save:');
            if (!pw) return;
            const confirm = prompt('Confirm the passphrase:');
            if (confirm !== pw) { $('gameSaveOut').textContent = 'Passphrases did not match.'; return; }
            const camp = state.campaigns.find(c => c.id === state.selectedCampaign);
            const slug = (camp?.slug || 'campaign') + '.ttdm';
            $('gameSaveOut').textContent = 'Generating encrypted game save…';
            try {
                await downloadEncrypted('/api/saves/game/export',
                    { campaign_id: state.selectedCampaign, passphrase: pw }, slug);
                $('gameSaveOut').textContent = `Downloaded ${slug}.`;
            } catch (e) { $('gameSaveOut').textContent = `Error: ${e.message}`; }
        };
    }

    if ($('btnImportGame')) {
        $('btnImportGame').onclick = async () => {
            const f = $('importGameFile').files[0];
            if (!f) { $('gameSaveOut').textContent = 'Pick a .ttdm file first.'; return; }
            const pw = prompt('Passphrase for the game save:');
            if (!pw) return;
            $('gameSaveOut').textContent = 'Decrypting and importing…';
            const fd = new FormData();
            fd.append('file', f);
            fd.append('passphrase', pw);
            fd.append('replace', $('importReplace').checked ? 'true' : 'false');
            try {
                const r = await fetch('/api/saves/game/import', { method: 'POST', body: fd });
                const res = await r.json();
                if (r.status === 409) {
                    $('gameSaveOut').textContent =
                        `A campaign with the same id already exists. Tick "Replace if same id exists" to overwrite.`;
                    return;
                }
                if (!r.ok) throw new Error(res.error || 'import failed');
                $('gameSaveOut').textContent = `Imported. Campaign id: ${res.campaign_id}`;
                await refreshAll();
            } catch (e) { $('gameSaveOut').textContent = `Error: ${e.message}`; }
        };
    }

    // Keep the "current campaign" label in the Save panel in sync.
    window._updateCampaignLabel = () => {
        const el = $('currentCampaignLabel');
        if (!el) return;
        const c = state.campaigns?.find(c => c.id === state.selectedCampaign);
        el.textContent = c ? c.name : '(no campaign selected)';
    };

    // ===== Character View Toggle =====
    const viewListBtn = $('viewList');
    const viewCardsBtn = $('viewCards');
    const charListDiv = $('characterList');
    const charCardsDiv = $('characterCards');

    if (viewListBtn && viewCardsBtn) {
        viewListBtn.onclick = () => {
            state.viewMode = 'list';
            viewListBtn.classList.add('active');
            viewCardsBtn.classList.remove('active');
            charListDiv.style.display = 'block';
            charCardsDiv.style.display = 'none';
        };
        viewCardsBtn.onclick = () => {
            state.viewMode = 'cards';
            viewCardsBtn.classList.add('active');
            viewListBtn.classList.remove('active');
            charListDiv.style.display = 'none';
            charCardsDiv.style.display = 'grid';
        };
    }

    // Show deleted checkbox
    const showDeletedCheckbox = $('showDeleted');
    if (showDeletedCheckbox) {
        showDeletedCheckbox.onchange = () => {
            state.showDeleted = showDeletedCheckbox.checked;
            loadCampaigns();
            loadCharacters();
        };
    }

    // Add to session button
    const addToSessionBtn = $('addToSession');
    if (addToSessionBtn) {
        addToSessionBtn.onclick = () => {
            const select = $('addCharacterSelect');
            window.control.addToSession(select.value);
        };
    }

    // Modal buttons
    const saveEditBtn = $('saveCharacterEdit');
    if (saveEditBtn) {
        saveEditBtn.onclick = () => window.control.saveCharacterEdit();
    }

    const uploadImgBtn = $('uploadCharImage');
    if (uploadImgBtn) {
        uploadImgBtn.onclick = () => window.control.uploadCharacterImage();
    }

    const removeImgBtn = $('removeCharImage');
    if (removeImgBtn) {
        removeImgBtn.onclick = () => window.control.removeCharacterImage();
    }

    // Close modal on backdrop click
    const modal = $('editCharacterModal');
    if (modal) {
        modal.onclick = (e) => {
            if (e.target === modal) closeEditModal();
        };
    }

    await refreshAll();
});
