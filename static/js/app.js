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

    renderEntityList() {
        const list = document.getElementById('entityList');
        list.innerHTML = '';

        for (const entity of this.entities) {
            const item = document.createElement('div');
            item.className = 'entity-item' + (this.selectedEntity?.id === entity.id ? ' selected' : '');
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
                const targetName = parts.slice(1).join(' ');
                const target = this.entities.find(e => e.name.toLowerCase().includes(targetName.toLowerCase()));
                if (!target) {
                    this.addEvent({type: 'ERROR', payload: {message: `Target "${targetName}" not found`}});
                    return;
                }
                this.addEvent({type: 'SYSTEM', payload: {message: `Attacking ${target.name}...`}});
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

            case '/help':
                this.addEvent({type: 'SYSTEM', payload: {
                    message: 'Commands: /roll [dice] [mod] | /mode [MODE] | /advance | /narrate [context] | /attack [target] | /help',
                }});
                break;

            default:
                this.addEvent({type: 'ERROR', payload: {message: `Unknown command: ${command}. Type /help for commands.`}});
        }
    },

    async sendChat(message) {
        if (!this.campaign) return;

        const speaker = this.entities.find(e => e.entity_type === 'PC');
        const principal = null;

        this.addEvent({type: 'SYSTEM', payload: {message: 'Chat sent (requires principal context for full processing)'}});
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

        } catch (e) {
            console.error('Map render error:', e);
        }
    },

    selectEncounter(encounterId) {
        this.selectedEncounter = this.encounters.find(e => e.id === encounterId) || null;
        this.loadEncounterSlots();
    },
};

document.addEventListener('DOMContentLoaded', () => App.init());
