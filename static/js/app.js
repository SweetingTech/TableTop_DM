const App = {
    socket: null,
    campaign: null,
    campaigns: [],
    entities: [],
    encounters: [],
    selectedEntity: null,
    selectedEncounter: null,
    encounterSlots: [],
    maps: [],
    events: [],
    connected: false,
    // Session context (Phase 1)
    principalId: null,
    sessionId: null,
    members: [],
    controlledEntities: [],
    mapContext: null,

    async init() {
        this.initSocket();
        await this.loadCampaigns();
        this.setupEventListeners();
        this.showTab('feed');
    },

    initSocket() {
        this.socket = io({transports: ['websocket', 'polling']});

        this.socket.on('connect', () => {
            this.connected = true;
            document.getElementById('connIndicator').classList.add('connected');
            if (this.campaign) {
                this.socket.emit('join_campaign', {campaign_id: this.campaign.id});
            }
        });

        this.socket.on('disconnect', () => {
            this.connected = false;
            document.getElementById('connIndicator').classList.remove('connected');
        });

        this.socket.on('game_event', (data) => {
            this.addEvent(data);
        });

        this.socket.on('turn_advanced', (data) => {
            this.addEvent({type: 'SYSTEM', payload: {message: `Turn advanced. Current turn: ${data.current_turn_order}`}});
            this.loadEncounterSlots();
        });

        this.socket.on('error', (data) => {
            this.addEvent({type: 'ERROR', payload: {message: data.message}});
        });
    },

    setupEventListeners() {
        document.getElementById('commandInput').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.submitCommand();
            }
        });
    },

    showTab(tabName) {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        document.querySelector(`.tab[data-tab="${tabName}"]`).classList.add('active');
        document.getElementById(`tab-${tabName}`).classList.add('active');

        if (tabName === 'map' && this.campaign) {
            this.renderMap();
        }
    },

    async loadCampaigns() {
        try {
            const resp = await fetch('/api/campaigns');
            this.campaigns = await resp.json();
            if (this.campaigns.length > 0) {
                await this.selectCampaign(this.campaigns[0]);
            }
        } catch (e) {
            console.error('Failed to load campaigns:', e);
        }
    },

    async selectCampaign(campaign) {
        this.campaign = campaign;
        document.getElementById('campaignName').textContent = campaign.name;
        const modeBadge = document.getElementById('modeBadge');
        modeBadge.textContent = campaign.mode;
        modeBadge.className = 'mode-badge ' + campaign.mode;

        if (this.socket && this.connected) {
            this.socket.emit('join_campaign', {campaign_id: campaign.id});
        }

        await Promise.all([
            this.loadEntities(),
            this.loadEncounters(),
            this.loadMaps(),
        ]);

        // Load session context after entities are loaded (needs entity list for controlled_entities)
        await this.loadSessionContext();
    },

    async loadEntities() {
        if (!this.campaign) return;
        try {
            const resp = await fetch(`/api/campaigns/${this.campaign.id}/entities`);
            this.entities = await resp.json();
            this.renderEntityList();
            // Push new positions to the 3D renderer if it's already up.
            if (this._mapRenderer && this.mapContext) {
                this._mapRenderer.setEntities(this.entities);
                // POI fog-of-war re-evaluates whenever the player moves.
                this._refreshDiscoveredPOIs();
            }
            this._updateCombatHUD();
        } catch (e) {
            console.error('Failed to load entities:', e);
        }
    },

    async _refreshDiscoveredPOIs() {
        if (!this._mapRenderer || !this.mapContext?.mapId) return;
        const tier = this.mapContext.mapKind || 'ROOM';
        try {
            if (tier === 'ROOM') {
                // Pure-prox class-modulated discovery on the tactical tier.
                const own = (this.entities || []).find(e =>
                    this.controlledEntities?.includes(e.id) && e.public_sheet?.x !== undefined
                );
                if (!own) { this._mapRenderer.setPOIs([]); return; }
                const r = await fetch(
                    `/api/entities/${own.id}/discovered_pois?map_id=${this.mapContext.mapId}`
                );
                if (!r.ok) return;
                this._mapRenderer.setPOIs(await r.json());
            } else {
                // World / Area: show all (non-hidden) POIs with labels for click-to-drill.
                const r = await fetch(`/api/maps/${this.mapContext.mapId}/pois`);
                if (!r.ok) return;
                const all = await r.json();
                this._mapRenderer.setPOIs(all.filter(p => !p.is_hidden));
            }
        } catch (e) {
            console.error('POI refresh failed:', e);
        }
    },

    async loadEncounters() {
        if (!this.campaign) return;
        try {
            const resp = await fetch(`/api/campaigns/${this.campaign.id}/encounters`);
            this.encounters = await resp.json();
            this.renderEncounterSelect();
            if (this.encounters.length > 0) {
                this.selectedEncounter = this.encounters[0];
                await this.loadEncounterSlots();
            }
        } catch (e) {
            console.error('Failed to load encounters:', e);
        }
    },

    async loadEncounterSlots() {
        if (!this.selectedEncounter) return;
        try {
            const resp = await fetch(`/api/encounters/${this.selectedEncounter.id}/slots`);
            this.encounterSlots = await resp.json();
            this.renderInitiativeTracker();
            this._updateCombatHUD();
        } catch (e) {
            console.error('Failed to load encounter slots:', e);
        }
    },

    // ---- Combat HUD (Phase 5) ----
    // JRPG-style menu visible only when:
    //   - campaign.mode === 'COMBAT'
    //   - the encounter's active slot belongs to a PC the player controls
    // In AI-only mode no human is around to click; the HUD stays hidden and
    // the AI policy drives the same /api/propose endpoints.

    _updateCombatHUD() {
        const hud = document.getElementById('combatHUD');
        if (!hud) return;
        const inCombat = this.campaign?.mode === 'COMBAT';
        const activeSlot = (this.encounterSlots || []).find(s => s.is_active);
        const activeEntity = activeSlot
            ? (this.entities || []).find(e => e.id === activeSlot.entity_id)
            : null;
        const isMine = activeEntity && this.canControl(activeEntity.id);
        if (inCombat && isMine) {
            hud.style.display = 'block';
            document.getElementById('combatActor').textContent =
                `${activeEntity.name} • ${activeSlot.ap_current ?? 0} AP`;
        } else {
            hud.style.display = 'none';
            this._combatPendingClick = null;
        }
    },

    /** Dispatcher for the JRPG-style combat menu buttons. */
    async combatChoose(cmd) {
        const promptEl = document.getElementById('combatPrompt');
        const setPrompt = (msg, active = false) => {
            promptEl.textContent = msg;
            promptEl.classList.toggle('active', !!active);
        };
        const activeSlot = (this.encounterSlots || []).find(s => s.is_active);
        const me = activeSlot ? (this.entities || []).find(e => e.id === activeSlot.entity_id) : null;
        if (!me) { setPrompt('No active actor.'); return; }
        this.selectedEntity = me;

        switch (cmd) {
            case 'fight':
                setPrompt('Resolving attack…');
                await this.quickAttack();
                setPrompt('');
                break;
            case 'item':
                setPrompt('No items in inventory yet.', true);
                break;
            case 'spell': {
                const spells = (me.public_sheet?.spells) || [];
                if (!spells.length) {
                    setPrompt('No spells prepared.', true);
                } else {
                    setPrompt(`Spells: ${spells.join(', ')} — selection UI coming soon.`, true);
                }
                break;
            }
            case 'move':
                this._combatPendingClick = me.id;
                setPrompt('Click a tile on the map (or use WASD) to move.', true);
                break;
            case 'endturn':
                setPrompt('Ending turn…');
                await this.quickEndTurn();
                setPrompt('');
                break;
            case 'flee':
                setPrompt('Attempting to disengage…');
                try {
                    const result = await this.proposeAction('FLEE', { entity_id: me.id });
                    if (result?.tool_result?.success) {
                        setPrompt('Disengaged.');
                    } else {
                        setPrompt('Disengage failed.');
                    }
                } catch (e) {
                    setPrompt(`Flee error: ${e.message}`, true);
                }
                break;
        }
    },

    async loadMaps() {
        if (!this.campaign) return;
        try {
            const resp = await fetch(`/api/campaigns/${this.campaign.id}/maps`);
            this.maps = await resp.json();
        } catch (e) {
            console.error('Failed to load maps:', e);
        }
    },

    async loadSessionContext() {
        if (!this.campaign) return;

        // Load campaign members
        try {
            const resp = await fetch(`/api/campaigns/${this.campaign.id}/members`);
            this.members = await resp.json();
        } catch (e) {
            console.error('Failed to load members:', e);
            return;
        }

        // Auto-select first HUMAN principal (demo mode - production would use real auth)
        const humanMember = this.members.find(m => m.principal_type === 'HUMAN');
        if (humanMember) {
            this.principalId = humanMember.principal_id;
            console.log('Principal context set:', this.principalId, humanMember.display_name);
            // Update UI
            const nameEl = document.getElementById('principalName');
            if (nameEl) nameEl.textContent = humanMember.display_name;
        }

        // Load or create active session
        try {
            const resp = await fetch(`/api/campaigns/${this.campaign.id}/resume`, {method: 'POST'});
            const data = await resp.json();
            if (data.session) {
                this.sessionId = data.session.id;
                console.log('Session context set:', this.sessionId);
                // Update UI
                const sessionEl = document.getElementById('sessionIndicator');
                if (sessionEl) sessionEl.classList.add('active');

                // Load session resume data (chat history, story state, party)
                await this.loadSessionResume();
            }
        } catch (e) {
            console.error('Failed to load session:', e);
        }

        // Compute which entities this principal controls
        this.controlledEntities = this.entities
            .filter(e => e.controller_principal_id === this.principalId)
            .map(e => e.id);
        console.log('Controlled entities:', this.controlledEntities.length);

        // Re-render entity list to show controlled indicators
        this.renderEntityList();
    },

    async loadSessionResume() {
        if (!this.sessionId) return;

        try {
            const resp = await fetch(`/api/sessions/${this.sessionId}/resume_data`);
            const data = await resp.json();

            // Store story state
            this.storyState = data.story_state;

            // Store party info
            this.party = data.party || [];

            // Load chat history into event feed
            if (data.chat_history && data.chat_history.length > 0) {
                this.addEvent({
                    type: 'SYSTEM',
                    payload: {message: `--- Resuming session: ${data.chat_history.length} messages loaded ---`}
                });

                for (const msg of data.chat_history) {
                    this.addHistoryEvent(msg);
                }

                this.addEvent({
                    type: 'SYSTEM',
                    payload: {message: '--- Session resumed ---'}
                });
            }

            // Update story state UI if available
            this.updateStoryStateUI();

            console.log('Session resumed with', data.chat_history?.length || 0, 'messages');
        } catch (e) {
            console.error('Failed to load session resume data:', e);
        }
    },

    addHistoryEvent(data) {
        // Add a historical event (with original timestamp)
        const feed = document.getElementById('eventFeed');
        const type = (data.event_type || 'system').toLowerCase();
        const payload = data.payload || {};

        const item = document.createElement('div');
        item.className = `event-item ${type} history`;

        // Use original timestamp
        let timestamp = '--:--:--';
        if (data.created_at) {
            const d = new Date(data.created_at);
            timestamp = d.toLocaleTimeString('en-US', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'});
        }

        let content = `<span class="timestamp">${timestamp}</span>`;

        if (type === 'narration') {
            content += payload.narration || payload.message || JSON.stringify(payload);
        } else if (type === 'dialogue' || type === 'chat') {
            const speaker = data.speaker_name || payload.speaker || 'Unknown';
            const msg = payload.dialogue || payload.message || '';
            content += `<span class="speaker">${speaker}:</span> ${msg}`;
        } else if (type === 'action') {
            content += `<strong>${payload.action_type || 'Action'}</strong>`;
            if (payload.result) {
                const res = typeof payload.result === 'string' ? payload.result : JSON.stringify(payload.result);
                content += `<div style="margin-top:4px;font-size:12px;color:var(--text-secondary)">${res.substring(0, 200)}</div>`;
            }
        } else {
            content += payload.message || JSON.stringify(payload).substring(0, 200);
        }

        item.innerHTML = content;
        feed.appendChild(item);
    },

    updateStoryStateUI() {
        if (!this.storyState) return;

        // Update story state indicators if they exist
        const locationEl = document.getElementById('currentLocation');
        if (locationEl && this.storyState.current_location) {
            locationEl.textContent = this.storyState.current_location;
        }

        const timeEl = document.getElementById('gameTime');
        if (timeEl && this.storyState.game_time) {
            timeEl.textContent = this.storyState.game_time;
        }
    },

    canControl(entityId) {
        if (!this.principalId) return false;
        // GMs can control any entity
        const member = this.members.find(m => m.principal_id === this.principalId);
        if (member?.role === 'GM') return true;
        // Otherwise check if principal controls this entity
        return this.controlledEntities.includes(entityId);
    },

    async proposeAction(actionType, params) {
        if (!this.campaign || !this.principalId || !this.sessionId) {
            this.addEvent({type: 'ERROR', payload: {message: 'Missing session context. Reload the page.'}});
            return null;
        }

        try {
            const body = {
                action_type: actionType,
                params: params,
                principal_id: this.principalId,
                campaign_id: this.campaign.id,
                session_id: this.sessionId,
                encounter_id: this.selectedEncounter?.id || null,
            };

            const resp = await fetch('/api/propose', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            });

            const data = await resp.json();
            if (data.error) {
                this.addEvent({type: 'ERROR', payload: {message: data.error}});
                return null;
            }

            // Refresh state after action
            await this.loadEntities();
            if (this.selectedEncounter) {
                await this.loadEncounterSlots();
            }

            return data;
        } catch (e) {
            this.addEvent({type: 'ERROR', payload: {message: 'Action failed: ' + e.message}});
            return null;
        }
    },

    renderEntityList() {
        const list = document.getElementById('entityList');
        list.innerHTML = '';

        for (const entity of this.entities) {
            const item = document.createElement('div');
            const isSelected = this.selectedEntity?.id === entity.id;
            const isControlled = this.controlledEntities.includes(entity.id);
            item.className = 'entity-item' +
                (isSelected ? ' selected' : '') +
                (isControlled ? ' controlled' : '');
            item.onclick = () => this.selectEntity(entity);

            const hpPct = entity.hp_max > 0 ? (entity.hp_current / entity.hp_max * 100) : 100;
            const hpClass = hpPct > 60 ? 'high' : hpPct > 30 ? 'medium' : 'low';
            const icon = this.getEntityIcon(entity.entity_type);

            item.innerHTML = `
                <div class="entity-icon ${entity.entity_type}">${icon}</div>
                <span>${entity.name}</span>
                ${entity.hp_max > 0 ? `<div class="hp-bar-mini"><div class="fill ${hpClass}" style="width:${hpPct}%"></div></div>` : ''}
            `;
            list.appendChild(item);
        }
    },

    getEntityIcon(type) {
        const icons = {PC:'P', NPC:'N', MONSTER:'M', GOD:'G', LOCATION:'L', ITEM:'I'};
        return icons[type] || '?';
    },

    selectEntity(entity) {
        this.selectedEntity = entity;
        this.renderEntityList();
        this.renderEntityDetail();
        this.updateMapCursor();
    },

    updateMapCursor() {
        const canvas = document.getElementById('mapCanvas');
        const hint = document.getElementById('mapHint');

        if (this.selectedEntity && this.canControl(this.selectedEntity.id)) {
            canvas?.classList.add('can-move');
            if (hint) {
                hint.textContent = `Click to move ${this.selectedEntity.name}`;
                hint.classList.remove('hidden');
            }
        } else {
            canvas?.classList.remove('can-move');
            if (hint) {
                hint.textContent = 'Select a controlled entity to move';
                hint.classList.add('hidden');
            }
        }
    },

    renderEntityDetail() {
        const panel = document.getElementById('entityDetail');
        if (!this.selectedEntity) {
            panel.innerHTML = '<div class="empty-state"><div class="icon">&#9876;</div><p>Select an entity</p></div>';
            return;
        }

        const e = this.selectedEntity;
        const hpPct = e.hp_max > 0 ? (e.hp_current / e.hp_max * 100) : 100;
        const hpClass = hpPct > 60 ? '#00ff88' : hpPct > 30 ? '#ffb74d' : '#ff4444';
        const sheet = e.public_sheet || {};

        let sheetHtml = '';
        for (const [key, val] of Object.entries(sheet)) {
            if (typeof val !== 'object') {
                sheetHtml += `<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:12px;border-bottom:1px solid var(--border-color)"><span style="color:var(--text-secondary)">${key}</span><span>${val}</span></div>`;
            }
        }

        panel.innerHTML = `
            <h3>${e.name}</h3>
            <div style="font-size:12px;color:var(--text-secondary);margin-bottom:12px">${e.entity_type} ${e.controlled_by ? '| ' + e.controlled_by : ''}</div>
            ${e.hp_max > 0 ? `
            <div class="hp-bar"><div class="fill" style="width:${hpPct}%;background:${hpClass}"></div></div>
            <div class="stat-grid">
                <div class="stat-box"><div class="label">HP</div><div class="value hp">${e.hp_current}/${e.hp_max}</div></div>
                <div class="stat-box"><div class="label">AC</div><div class="value ac">${e.ac || '-'}</div></div>
                <div class="stat-box"><div class="label">Speed</div><div class="value speed">${e.speed || '-'}</div></div>
                <div class="stat-box"><div class="label">Type</div><div class="value" style="font-size:14px">${e.entity_type}</div></div>
            </div>
            ` : ''}
            ${sheetHtml ? `<div style="margin-top:12px">${sheetHtml}</div>` : ''}
        `;
    },

    renderEncounterSelect() {
        const sel = document.getElementById('encounterSelect');
        sel.innerHTML = '<option value="">No Encounter</option>';
        for (const enc of this.encounters) {
            sel.innerHTML += `<option value="${enc.id}" ${this.selectedEncounter?.id === enc.id ? 'selected' : ''}>${enc.name} (${enc.status})</option>`;
        }
    },

    renderInitiativeTracker() {
        const list = document.getElementById('initiativeList');
        list.innerHTML = '';

        if (this.encounterSlots.length === 0) {
            list.innerHTML = '<div class="empty-state" style="padding:16px"><p style="font-size:12px">No active encounter</p></div>';
            return;
        }

        for (const slot of this.encounterSlots) {
            const entity = this.entities.find(e => e.id === slot.entity_id);
            const name = entity?.name || slot.entity_name || 'Unknown';
            const isCurrent = this.selectedEncounter && slot.turn_order === this.selectedEncounter.current_turn_order;

            const item = document.createElement('div');
            item.className = 'initiative-item' + (isCurrent ? ' current' : '');
            item.innerHTML = `
                <span class="turn-order">${slot.turn_order}</span>
                <span>${name}</span>
                <span style="margin-left:auto;font-size:11px;color:var(--text-secondary)">${slot.initiative || ''}</span>
            `;
            list.appendChild(item);
        }
    },

    addEvent(data) {
        const feed = document.getElementById('eventFeed');
        const type = (data.type || data.event_type || 'system').toLowerCase();
        const payload = data.payload || data;

        const item = document.createElement('div');
        item.className = `event-item ${type}`;

        const now = new Date().toLocaleTimeString('en-US', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'});
        let content = `<span class="timestamp">${now}</span>`;

        if (type === 'narration') {
            content += payload.narration || payload.message || JSON.stringify(payload);
        } else if (type === 'dialogue' || type === 'chat') {
            const speaker = payload.speaker || 'Unknown';
            const msg = payload.dialogue || payload.message || '';
            content += `<span class="speaker">${speaker}:</span> ${msg}`;
        } else if (type === 'tool_call') {
            const tool = payload.tool_name || 'action';
            content += `<strong>${tool.replace(/_/g, ' ')}</strong>`;
            if (payload.rolls) {
                for (const r of payload.rolls) {
                    content += `<div class="roll-result">${r.breakdown || JSON.stringify(r)}</div>`;
                }
            }
            if (payload.result) {
                const res = typeof payload.result === 'string' ? payload.result : JSON.stringify(payload.result);
                content += `<div style="margin-top:4px;font-size:12px;color:var(--text-secondary)">${res.substring(0, 200)}</div>`;
            }
        } else if (type === 'error') {
            item.classList.add('error');
            content += payload.message || payload.error || JSON.stringify(payload);
        } else {
            content += payload.message || JSON.stringify(payload).substring(0, 200);
        }

        item.innerHTML = content;
        feed.appendChild(item);
        feed.scrollTop = feed.scrollHeight;

        this.events.push(data);
    },

    async submitCommand() {
        const input = document.getElementById('commandInput');
        const cmd = input.value.trim();
        if (!cmd) return;
        input.value = '';

        this.addEvent({type: 'CHAT', payload: {speaker: 'You', message: cmd}});

        if (cmd.startsWith('/')) {
            await this.processSlashCommand(cmd);
        } else {
            await this.sendChat(cmd);
        }
    },

    async processSlashCommand(cmd) {
        const parts = cmd.split(' ');
        const command = parts[0].toLowerCase();

        switch (command) {
            case '/roll': {
                const notation = parts[1] || '1d20';
                const modifier = parseInt(parts[2]) || 0;
                try {
                    const resp = await fetch('/api/dice/roll', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({notation, modifier}),
                    });
                    const data = await resp.json();
                    this.addEvent({type: 'TOOL_CALL', payload: {
                        tool_name: 'dice_roll',
                        rolls: [data],
                        result: `${data.breakdown}`,
                    }});
                } catch (e) {
                    this.addEvent({type: 'ERROR', payload: {message: 'Roll failed: ' + e.message}});
                }
                break;
            }

            case '/attack': {
                if (!this.selectedEntity || !this.campaign) {
                    this.addEvent({type: 'ERROR', payload: {message: 'Select an entity first'}});
                    return;
                }
                if (!this.canControl(this.selectedEntity.id)) {
                    this.addEvent({type: 'ERROR', payload: {message: 'You cannot control this entity'}});
                    return;
                }
                const targetName = parts.slice(1).join(' ');
                const target = this.entities.find(e => e.name.toLowerCase().includes(targetName.toLowerCase()));
                if (!target) {
                    this.addEvent({type: 'ERROR', payload: {message: `Target "${targetName}" not found`}});
                    return;
                }

                this.addEvent({type: 'SYSTEM', payload: {message: `${this.selectedEntity.name} attacks ${target.name}...`}});

                const result = await this.proposeAction('ATTACK', {
                    attacker_id: this.selectedEntity.id,
                    target_id: target.id,
                    weapon: 'melee',
                });

                if (result && result.tool_result) {
                    const tr = result.tool_result;
                    let msg = tr.hits ?
                        `Hit! Rolled ${tr.attack_roll} vs AC ${tr.target_ac}. Dealt ${tr.damage} damage.` :
                        `Miss! Rolled ${tr.attack_roll} vs AC ${tr.target_ac}.`;
                    if (tr.natural_20) msg = 'CRITICAL HIT! ' + msg;
                    if (tr.natural_1) msg = 'Critical miss! ' + msg;
                    if (tr.target_down) msg += ' Target is down!';

                    this.addEvent({type: 'TOOL_CALL', payload: {
                        tool_name: 'resolve_attack',
                        rolls: result.rolls || [],
                        result: msg,
                    }});
                }
                break;
            }

            case '/endturn': {
                if (!this.selectedEncounter) {
                    this.addEvent({type: 'ERROR', payload: {message: 'No encounter selected'}});
                    return;
                }
                if (!this.selectedEntity) {
                    this.addEvent({type: 'ERROR', payload: {message: 'Select your entity first'}});
                    return;
                }

                const result = await this.proposeAction('END_TURN', {
                    entity_id: this.selectedEntity.id,
                });

                if (result?.tool_result?.success) {
                    this.addEvent({type: 'SYSTEM', payload: {message: 'Turn ended'}});
                }
                break;
            }

            case '/mode': {
                const newMode = (parts[1] || '').toUpperCase();
                if (!['EXPLORATION','COMBAT','DIALOGUE','CUTSCENE','DOWNTIME'].includes(newMode)) {
                    this.addEvent({type: 'ERROR', payload: {message: 'Valid modes: EXPLORATION, COMBAT, DIALOGUE, CUTSCENE, DOWNTIME'}});
                    return;
                }
                try {
                    const resp = await fetch(`/api/campaigns/${this.campaign.id}/mode`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({mode: newMode}),
                    });
                    const data = await resp.json();
                    this.addEvent({type: 'SYSTEM', payload: {message: `Mode changed to ${newMode}`}});
                    const modeBadge = document.getElementById('modeBadge');
                    modeBadge.textContent = newMode;
                    modeBadge.className = 'mode-badge ' + newMode;
                } catch (e) {
                    this.addEvent({type: 'ERROR', payload: {message: e.message}});
                }
                break;
            }

            case '/advance': {
                if (!this.selectedEncounter) {
                    this.addEvent({type: 'ERROR', payload: {message: 'No encounter selected'}});
                    return;
                }
                try {
                    const resp = await fetch(`/api/encounters/${this.selectedEncounter.id}/advance`, {method: 'POST'});
                    const data = await resp.json();
                    this.addEvent({type: 'SYSTEM', payload: {message: `Turn advanced to order ${data.current_turn_order}`}});
                    await this.loadEncounterSlots();
                } catch (e) {
                    this.addEvent({type: 'ERROR', payload: {message: e.message}});
                }
                break;
            }

            case '/narrate': {
                const text = parts.slice(1).join(' ');
                try {
                    const resp = await fetch('/api/narrate', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({event_data: {}, context: text}),
                    });
                    const data = await resp.json();
                    if (data.narration) {
                        this.addEvent({type: 'NARRATION', payload: {narration: data.narration}});
                    } else {
                        this.addEvent({type: 'ERROR', payload: {message: data.error || 'Narration failed'}});
                    }
                } catch (e) {
                    this.addEvent({type: 'ERROR', payload: {message: e.message}});
                }
                break;
            }

            case '/say': {
                // Parse @target from message: /say @npc_name message
                const msgText = parts.slice(1).join(' ');
                const targetMatch = msgText.match(/^@(\S+)\s*(.*)/);
                let targetEntity = null;
                let message = msgText;

                if (targetMatch) {
                    const targetName = targetMatch[1];
                    targetEntity = this.entities.find(e =>
                        e.name.toLowerCase().includes(targetName.toLowerCase())
                    );
                    message = targetMatch[2] || '';
                }

                if (!message.trim()) {
                    this.addEvent({type: 'ERROR', payload: {message: 'Usage: /say [@target] message'}});
                    return;
                }

                if (targetEntity) {
                    this.addEvent({type: 'SYSTEM', payload: {message: `Speaking to ${targetEntity.name}...`}});
                }

                await this.sendChat(message, targetEntity?.id);
                break;
            }

            case '/help':
                this.addEvent({type: 'SYSTEM', payload: {
                    message: 'Commands: /roll [dice] [mod] | /attack [target] | /endturn | /mode [MODE] | /advance | /narrate [context] | /say [@target] msg | /help',
                }});
                break;

            default:
                this.addEvent({type: 'ERROR', payload: {message: `Unknown command: ${command}. Type /help for commands.`}});
        }
    },

    async sendChat(message, targetEntityId = null) {
        if (!this.campaign || !this.principalId || !this.sessionId) {
            this.addEvent({type: 'ERROR', payload: {message: 'Session context not loaded. Reload the page.'}});
            return;
        }

        // Find speaker entity (selected if controlled, else first controlled entity)
        let speakerEntity = this.selectedEntity;
        if (!speakerEntity || !this.canControl(speakerEntity.id)) {
            speakerEntity = this.entities.find(e => this.controlledEntities.includes(e.id));
        }

        if (!speakerEntity) {
            this.addEvent({type: 'ERROR', payload: {message: 'No character to speak as'}});
            return;
        }

        try {
            const body = {
                campaign_id: this.campaign.id,
                session_id: this.sessionId,
                speaker_entity_id: speakerEntity.id,
                speaker_principal_id: this.principalId,
                message: message,
            };

            if (targetEntityId) {
                body.target_entity_id = targetEntityId;
            }

            const resp = await fetch('/api/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            });

            const data = await resp.json();
            if (data.error) {
                this.addEvent({type: 'ERROR', payload: {message: data.error}});
            }
            // Chat events will arrive via WebSocket
        } catch (e) {
            this.addEvent({type: 'ERROR', payload: {message: 'Chat failed: ' + e.message}});
        }
    },

    async advanceTurn() {
        if (!this.selectedEncounter) return;
        try {
            const resp = await fetch(`/api/encounters/${this.selectedEncounter.id}/advance`, {method: 'POST'});
            const data = await resp.json();
            this.addEvent({type: 'SYSTEM', payload: {message: `Turn advanced`}});
            await this.loadEncounterSlots();
        } catch (e) {
            this.addEvent({type: 'ERROR', payload: {message: e.message}});
        }
    },

    async rollDice() {
        try {
            const resp = await fetch('/api/dice/roll', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({notation: '1d20', modifier: 0}),
            });
            const data = await resp.json();
            this.addEvent({type: 'TOOL_CALL', payload: {
                tool_name: 'quick_roll',
                rolls: [data],
                result: data.breakdown,
            }});
        } catch (e) {
            this.addEvent({type: 'ERROR', payload: {message: e.message}});
        }
    },

    async requestNarration() {
        try {
            const resp = await fetch('/api/narrate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    event_data: {campaign: this.campaign?.name},
                    context: 'Describe the current scene in the campaign.',
                }),
            });
            const data = await resp.json();
            if (data.narration) {
                this.addEvent({type: 'NARRATION', payload: {narration: data.narration}});
            }
        } catch (e) {
            this.addEvent({type: 'ERROR', payload: {message: e.message}});
        }
    },

    async quickAttack() {
        // Attack requires: a selected entity we control, and a target
        if (!this.selectedEntity) {
            this.addEvent({type: 'ERROR', payload: {message: 'Select your character first'}});
            return;
        }
        if (!this.canControl(this.selectedEntity.id)) {
            this.addEvent({type: 'ERROR', payload: {message: 'You cannot control this entity'}});
            return;
        }

        // Find a valid target (first enemy entity)
        const targets = this.entities.filter(e =>
            e.id !== this.selectedEntity.id &&
            e.hp_current > 0 &&
            (e.entity_type === 'MONSTER' || e.entity_type === 'NPC')
        );

        if (targets.length === 0) {
            this.addEvent({type: 'ERROR', payload: {message: 'No valid targets. Use /attack [name] to specify.'}});
            return;
        }

        const target = targets[0];
        this.addEvent({type: 'SYSTEM', payload: {message: `${this.selectedEntity.name} attacks ${target.name}...`}});

        const result = await this.proposeAction('ATTACK', {
            attacker_id: this.selectedEntity.id,
            target_id: target.id,
            weapon: 'melee',
        });

        if (result && result.tool_result) {
            const tr = result.tool_result;
            let msg = tr.hits ?
                `Hit! Rolled ${tr.attack_roll} vs AC ${tr.target_ac}. Dealt ${tr.damage} damage.` :
                `Miss! Rolled ${tr.attack_roll} vs AC ${tr.target_ac}.`;
            if (tr.natural_20) msg = 'CRITICAL HIT! ' + msg;
            if (tr.natural_1) msg = 'Critical miss! ' + msg;
            if (tr.target_down) msg += ' Target is down!';

            this.addEvent({type: 'TOOL_CALL', payload: {
                tool_name: 'resolve_attack',
                rolls: result.rolls || [],
                result: msg,
            }});
        }
    },

    async quickEndTurn() {
        if (!this.selectedEncounter) {
            this.addEvent({type: 'ERROR', payload: {message: 'No encounter active'}});
            return;
        }
        if (!this.selectedEntity) {
            this.addEvent({type: 'ERROR', payload: {message: 'Select your character first'}});
            return;
        }
        if (!this.canControl(this.selectedEntity.id)) {
            this.addEvent({type: 'ERROR', payload: {message: 'You cannot control this entity'}});
            return;
        }

        const result = await this.proposeAction('END_TURN', {
            entity_id: this.selectedEntity.id,
        });

        if (result?.tool_result?.success) {
            this.addEvent({type: 'SYSTEM', payload: {message: `${this.selectedEntity.name} ends their turn`}});
        }
    },

    // ---- Three.js map renderer integration (Phase 1) ----
    // Click-to-move (raycaster) + WASD come in Phase 3.

    _ensureMapRenderer() {
        if (this._mapRenderer) return this._mapRenderer;
        if (!window.MapRenderer) return null; // module still loading
        const canvas = document.getElementById('mapCanvas');
        if (!canvas) return null;
        this._mapRenderer = new window.MapRenderer(canvas);
        // Phase 3 — movement (only meaningful on the ROOM tier).
        this._mapRenderer.onTileClick = (gx, gy) => this._tryMoveTo(gx, gy);
        this._mapRenderer.onTileStep = (dx, dy) => this._tryStep(dx, dy);
        // Phase 6b — clicking a POI sprite. On World/Area, drill into target_map_id
        // if set. On Room, surface the POI's name/description as an event.
        this._mapRenderer.onPOIClick = (poi) => this._handlePOIClick(poi);
        return this._mapRenderer;
    },

    async _handlePOIClick(poi) {
        if (!poi) return;
        const tier = this.mapContext?.mapKind || 'ROOM';
        if (poi.target_map_id) {
            await this.drillIntoMap(poi.target_map_id);
            return;
        }
        if (tier === 'ROOM') {
            // Surface description as an event-feed entry.
            const desc = poi.description ? ` — ${poi.description}` : '';
            this.addEvent({type: 'SYSTEM', payload: {message: `Examining ${poi.name}${desc}`}});
        } else {
            // World/Area POI without a target — just acknowledge.
            this.addEvent({type: 'SYSTEM', payload: {message: `${poi.kind}: ${poi.name}`}});
        }
    },

    async _tryMoveTo(gx, gy) {
        if (this.mapContext?.mapKind && this.mapContext.mapKind !== 'ROOM') return;
        if (!this.selectedEntity) {
            this.addEvent({type: 'SYSTEM', payload: {message: 'Select your character first'}});
            return;
        }
        if (!this.canControl(this.selectedEntity.id)) {
            this.addEvent({type: 'ERROR', payload: {message: 'You cannot control this entity'}});
            return;
        }
        const result = await this.proposeAction('MOVE', {
            entity_id: this.selectedEntity.id,
            destination_x: gx,
            destination_y: gy,
        });
        if (result?.tool_result?.success) {
            await this.loadEntities(); // pulls new (x,y), pushes to renderer
        }
    },

    async _tryStep(dx, dy) {
        if (this.mapContext?.mapKind && this.mapContext.mapKind !== 'ROOM') return;
        // Default movement target = the player's controlled PC (not arbitrary
        // selected entity), so WASD always moves you.
        const own = (this.entities || []).find(e =>
            this.controlledEntities?.includes(e.id) && e.public_sheet?.x !== undefined
        );
        if (!own) return;
        const cx = own.public_sheet.x;
        const cy = own.public_sheet.y;
        await this._tryMoveTo(cx + dx, cy + dy);
    },

    renderMap() {
        const r = this._ensureMapRenderer();
        if (!r) {
            // Module still loading via importmap — retry shortly.
            setTimeout(() => this.renderMap(), 200);
            return;
        }
        if (!this.maps || this.maps.length === 0) {
            r.loadMap(null, null);
            r.setEntities([]);
            this._renderBreadcrumbs(null);
            return;
        }
        // Default to the deepest tier the campaign has — Room beats Area beats World.
        // Once the user navigates with the breadcrumbs we honor _currentMapId.
        if (!this._currentMapId || !this.maps.find(m => m.id === this._currentMapId)) {
            const order = { ROOM: 0, AREA: 1, WORLD: 2 };
            const sorted = [...this.maps].sort((a, b) =>
                (order[a.kind] ?? 0) - (order[b.kind] ?? 0)
            );
            this._currentMapId = sorted[0]?.id || this.maps[0]?.id;
        }
        this.loadAndRenderMap(this._currentMapId);
    },

    async loadAndRenderMap(mapId) {
        const r = this._ensureMapRenderer();
        if (!r) return;
        try {
            const resp = await fetch(`/api/maps/${mapId}`);
            const data = await resp.json();
            if (data.error) return;
            this._currentMapId = mapId;
            r.loadMap(data.map, data.nodes);
            // Only show entities on the map that hosts them. Right now entities
            // don't carry a current_map_id — show on the deepest (Room) only.
            const showEntities = (data.map.kind || 'ROOM') === 'ROOM';
            r.setEntities(showEntities ? (this.entities || []) : []);
            this.mapContext = {
                mapId: mapId,
                mapKind: data.map.kind,
                mapWidth: data.map.width || 20,
                mapHeight: data.map.height || 20,
            };
            // Camera follow only on Room tier — World/Area free pan.
            if (showEntities) {
                const own = (this.entities || []).find(e =>
                    this.controlledEntities?.includes(e.id) && e.public_sheet?.x !== undefined
                );
                if (own) r.focusOn(own.public_sheet.x, own.public_sheet.y);
            }
            this._renderBreadcrumbs(data.map);
            this._refreshDiscoveredPOIs();
        } catch (e) {
            console.error('Map render error:', e);
        }
    },

    /** Drilldown: load a child map. Called from breadcrumb child-links. */
    async drillIntoMap(childMapId) {
        await this.loadAndRenderMap(childMapId);
    },

    /** Zoom out one tier — load the parent map if there is one. */
    async zoomOutMap() {
        if (!this.mapContext?.mapId) return;
        const cur = this.maps.find(m => m.id === this.mapContext.mapId);
        if (!cur?.parent_map_id) return;
        await this.loadAndRenderMap(cur.parent_map_id);
    },

    async _renderBreadcrumbs(mapData) {
        const el = document.getElementById('mapBreadcrumbs');
        if (!el) return;
        if (!mapData) { el.innerHTML = ''; return; }

        // Walk parent chain (resolved client-side from this.maps).
        const chain = [];
        let cursor = mapData;
        const guard = new Set();
        while (cursor && !guard.has(cursor.id)) {
            guard.add(cursor.id);
            chain.unshift(cursor);
            if (!cursor.parent_map_id) break;
            cursor = this.maps.find(m => m.id === cursor.parent_map_id);
        }

        const parts = chain.map(m => {
            const isCurrent = m.id === mapData.id;
            const cls = isCurrent ? 'crumb current' : 'crumb';
            const label = `${m.kind || 'ROOM'}: ${m.name || 'Untitled'}`;
            if (isCurrent) return `<span class="${cls}">${label}</span>`;
            return `<span class="${cls}" onclick="App.loadAndRenderMap('${m.id}')">${label}</span>`;
        });

        // Pull child maps so the user can drill in. Lazy-fetch.
        let childrenHtml = '';
        try {
            const r = await fetch(`/api/maps/${mapData.id}/children`);
            const children = await r.json();
            if (Array.isArray(children) && children.length) {
                childrenHtml = children.map(c =>
                    `<span class="child-link" onclick="App.drillIntoMap('${c.id}')">↓ ${c.name}</span>`
                ).join('');
            }
        } catch (_) { /* non-fatal */ }

        el.innerHTML = parts.join('<span class="sep">›</span>') + childrenHtml;
        // Disable the zoom-out button when there's no parent.
        const btn = document.getElementById('btnZoomOut');
        if (btn) btn.disabled = !mapData.parent_map_id;
    },

    // Click-to-move stub (Phase 3 replaces with raycaster).
    async handleMapClick(_event) { /* Phase 3 */ },

    selectEncounter(encounterId) {
        this.selectedEncounter = this.encounters.find(e => e.id === encounterId) || null;
        this.loadEncounterSlots();
    },
};

document.addEventListener('DOMContentLoaded', () => App.init());
