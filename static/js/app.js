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
        } catch (e) {
            console.error('Failed to load entities:', e);
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
        } catch (e) {
            console.error('Failed to load encounter slots:', e);
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

    renderMap() {
        const canvas = document.getElementById('mapCanvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const container = canvas.parentElement;
        canvas.width = container.clientWidth;
        canvas.height = container.clientHeight;

        ctx.fillStyle = '#0a0a1a';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        if (this.maps.length === 0) {
            ctx.fillStyle = '#a0a0c0';
            ctx.font = '16px system-ui';
            ctx.textAlign = 'center';
            ctx.fillText('No maps loaded', canvas.width/2, canvas.height/2);
            return;
        }

        const map = this.maps[0];
        this.loadAndRenderMap(map.id);
    },

    async loadAndRenderMap(mapId) {
        try {
            const resp = await fetch(`/api/maps/${mapId}`);
            const data = await resp.json();
            if (data.error) return;

            const canvas = document.getElementById('mapCanvas');
            const ctx = canvas.getContext('2d');
            const mapData = data.map;
            const nodes = data.nodes;

            const cellSize = Math.min(
                (canvas.width - 40) / (mapData.width || 20),
                (canvas.height - 40) / (mapData.height || 20)
            );

            const offsetX = (canvas.width - cellSize * (mapData.width || 20)) / 2;
            const offsetY = (canvas.height - cellSize * (mapData.height || 20)) / 2;

            ctx.fillStyle = '#0a0a1a';
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            const terrainColors = {
                stone_floor: '#3a3a4a',
                grass: '#1a3a1a',
                dirt: '#3a2a1a',
                water: '#1a2a4a',
                sand: '#4a4a2a',
                wood: '#3a2a1a',
                wall: '#1a1a1a',
            };

            for (const node of nodes) {
                const x = offsetX + node.x * cellSize;
                const y = offsetY + node.y * cellSize;
                const terrain = node.terrain || {};
                const type = terrain.type || 'stone_floor';
                const isWall = node.collision_mask && node.collision_mask[0] === '1';

                ctx.fillStyle = isWall ? '#0a0a0a' : (terrainColors[type] || '#2a2a3a');
                ctx.fillRect(x, y, cellSize - 1, cellSize - 1);

                if (terrain.difficult) {
                    ctx.fillStyle = 'rgba(255, 136, 0, 0.3)';
                    ctx.fillRect(x, y, cellSize - 1, cellSize - 1);
                }
            }

            for (const entity of this.entities) {
                if (entity.entity_type === 'LOCATION') continue;
                const sheet = entity.public_sheet || {};
                const ex = sheet.x;
                const ey = sheet.y;
                if (ex !== undefined && ey !== undefined) {
                    const px = offsetX + ex * cellSize + cellSize/2;
                    const py = offsetY + ey * cellSize + cellSize/2;
                    const radius = cellSize * 0.35;

                    const colors = {PC: '#4caf50', NPC: '#42a5f5', MONSTER: '#ff4444', GOD: '#ce93d8'};
                    ctx.fillStyle = colors[entity.entity_type] || '#888';
                    ctx.beginPath();
                    ctx.arc(px, py, radius, 0, Math.PI * 2);
                    ctx.fill();

                    ctx.fillStyle = '#fff';
                    ctx.font = `${Math.max(8, cellSize * 0.3)}px system-ui`;
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(entity.name[0], px, py);
                }
            }

            ctx.fillStyle = '#a0a0c0';
            ctx.font = '12px system-ui';
            ctx.textAlign = 'left';
            ctx.fillText(mapData.name || 'Map', 12, canvas.height - 12);

            // Store map context for click-to-move
            this.mapContext = {
                cellSize: cellSize,
                offsetX: offsetX,
                offsetY: offsetY,
                mapId: mapId,
                mapWidth: mapData.width || 20,
                mapHeight: mapData.height || 20,
            };

            // Add click handler for movement
            canvas.onclick = (e) => this.handleMapClick(e);

        } catch (e) {
            console.error('Map render error:', e);
        }
    },

    async handleMapClick(event) {
        const canvas = document.getElementById('mapCanvas');
        const rect = canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;

        if (!this.mapContext || !this.selectedEntity) {
            this.addEvent({type: 'SYSTEM', payload: {message: 'Select an entity to move'}});
            return;
        }

        if (!this.canControl(this.selectedEntity.id)) {
            this.addEvent({type: 'ERROR', payload: {message: 'You cannot control this entity'}});
            return;
        }

        // Convert click to grid coordinates
        const gridX = Math.floor((x - this.mapContext.offsetX) / this.mapContext.cellSize);
        const gridY = Math.floor((y - this.mapContext.offsetY) / this.mapContext.cellSize);

        // Validate bounds
        if (gridX < 0 || gridX >= this.mapContext.mapWidth ||
            gridY < 0 || gridY >= this.mapContext.mapHeight) {
            return;
        }

        this.addEvent({type: 'SYSTEM', payload: {
            message: `Moving ${this.selectedEntity.name} to (${gridX}, ${gridY})...`
        }});

        const result = await this.proposeAction('MOVE', {
            entity_id: this.selectedEntity.id,
            destination_x: gridX,
            destination_y: gridY,
        });

        if (result?.tool_result?.success) {
            this.addEvent({type: 'SYSTEM', payload: {
                message: `${this.selectedEntity.name} moved to (${gridX}, ${gridY})`
            }});
            // Re-render map with updated positions
            this.renderMap();
        }
    },

    selectEncounter(encounterId) {
        this.selectedEncounter = this.encounters.find(e => e.id === encounterId) || null;
        this.loadEncounterSlots();
    },
};

document.addEventListener('DOMContentLoaded', () => App.init());
