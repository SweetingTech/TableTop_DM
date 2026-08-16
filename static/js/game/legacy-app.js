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
    playerState: null,
    isGM: false,
    viewedPrincipalId: null,
    lastEventSequence: null,
    seenEventIds: new Set(),
    joinTokens: {},

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
            this.joinRealtimeRooms();
            if (this.sessionId && this.principalId) {
                this.loadPlayerStateSnapshot({silentTransient: true});
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
            const label = data.active_entity_name || data.current_entity_name || data.current_turn_order || 'next actor';
            this.addEvent({type: 'SYSTEM', payload: {message: `Turn advanced. Current turn: ${label}`}});
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
                this._mapRenderer.setEntities(this.entities, this.controlledEntities);
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

        this.populatePrincipalSelector();

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

                // Load authoritative per-principal snapshot first; fall back to
                // legacy resume data only if the snapshot endpoint is unavailable.
                const loadedSnapshot = await this.loadPlayerStateSnapshot();
                if (!loadedSnapshot) await this.loadSessionResume();
            }
        } catch (e) {
            console.error('Failed to load session:', e);
        }

        // Compute which entities this principal controls when the snapshot did not
        // already provide the canonical control list.
        // GMs can drive any PC in the campaign (canControl returns true for them
        // unconditionally on the server). Mirror that here so the renderer's
        // halo + movement-target logic treats every PC as "yours" when you're
        // the GM. Regular players still only see halos on the PCs explicitly
        // tied to their principal_id.
        const isGM = this.isAuthenticatedGM();
        if (!this.playerState) {
            this.controlledEntities = this.entities
                .filter(e => isGM ? e.entity_type === 'PC' : e.controller_principal_id === this.principalId)
                .map(e => e.id);
        }
        console.log('Controlled entities:', this.controlledEntities.length, isGM ? '(GM)' : '');

        // Re-render entity list to show controlled indicators
        this.renderEntityList();
        this.joinRealtimeRooms();
    },

    isAuthenticatedGM() {
        const member = (this.members || []).find(m => m.principal_id === this.principalId);
        return member?.role === 'GM' || member?.principal_type === 'SYSTEM';
    },

    localJoinTokenFor(member) {
        if (!member?.principal_id) return null;
        const storageKey = this.campaign
            ? `ttdm_join_token:${this.campaign.id}:${member.principal_id}`
            : `ttdm_join_token:${member.principal_id}`;
        const stored = this.joinTokens[member.principal_id] || localStorage.getItem(storageKey);
        if (stored) return stored;
        const prefix = member.role === 'GM' ? 'dm' : 'player';
        return `${prefix}-smoke-join-${member.principal_id}`;
    },

    authenticatedMember() {
        return (this.members || []).find(m => m.principal_id === this.principalId) || null;
    },

    activeViewMember() {
        const viewId = this.viewedPrincipalId || this.principalId;
        return (this.members || []).find(m => m.principal_id === viewId) || null;
    },

    updatePrincipalIdentityUI() {
        const select = document.getElementById('principalSelect');
        const nameEl = document.getElementById('principalName');
        const authMember = this.authenticatedMember();
        const viewMember = this.activeViewMember() || authMember;

        if (nameEl) {
            const label = viewMember?.display_name || this.principalId || '--';
            nameEl.textContent = this.isGM && this.viewedPrincipalId && this.viewedPrincipalId !== this.principalId
                ? `${label} (GM view)`
                : label;
        }

        if (!select) return;
        select.innerHTML = '';
        if (this.isGM) {
            for (const member of this.members || []) {
                const option = document.createElement('option');
                option.value = member.principal_id;
                option.textContent = `${member.display_name} (${member.role})`;
                option.selected = member.principal_id === (this.viewedPrincipalId || this.principalId);
                select.appendChild(option);
            }
            select.style.display = (this.members || []).length > 1 ? 'inline-block' : 'none';
        } else {
            select.style.display = 'none';
            if (authMember) {
                const option = document.createElement('option');
                option.value = authMember.principal_id;
                option.textContent = `${authMember.display_name} (${authMember.role})`;
                option.selected = true;
                select.appendChild(option);
            }
        }
    },

    updateDmControls() {
        document.querySelectorAll('.dm-only-control').forEach((el) => {
            el.style.display = this.isGM ? '' : 'none';
            if ('disabled' in el) el.disabled = !this.isGM;
            el.setAttribute('aria-hidden', this.isGM ? 'false' : 'true');
        });
    },

    authQueryString() {
        const params = new URLSearchParams();
        params.set('principal_id', this.principalId);
        const token = this.localJoinTokenFor(this.authenticatedMember());
        if (token) params.set('join_token', token);
        return params;
    },

    populatePrincipalSelector() {
        const storageKey = this.campaign ? `ttdm_principal_id:${this.campaign.id}` : 'ttdm_principal_id';
        const params = new URLSearchParams(window.location.search);
        const requestedFromUrl = params.get('principal_id');
        const tokenFromUrl = params.get('join_token') || params.get('invite_token');
        const requested = requestedFromUrl || localStorage.getItem(storageKey);
        let valid = (this.members || []).find(m => m.principal_id === requested);
        if (!requestedFromUrl && valid?.role === 'GM') {
            valid = null;
        }
        const defaultMember = valid
            || (this.members || []).find(m => m.role === 'PLAYER' && m.principal_type === 'HUMAN')
            || (this.members || []).find(m => m.role === 'PLAYER')
            || (this.members || []).find(m => m.principal_type === 'HUMAN')
            || (this.members || []).find(m => m.role === 'GM')
            || (this.members || [])[0];

        if (!defaultMember) return;
        this.principalId = defaultMember.principal_id;
        this.viewedPrincipalId = null;
        localStorage.setItem(storageKey, this.principalId);
        if (tokenFromUrl && requestedFromUrl && requestedFromUrl === this.principalId) {
            const tokenKey = this.campaign
                ? `ttdm_join_token:${this.campaign.id}:${this.principalId}`
                : `ttdm_join_token:${this.principalId}`;
            localStorage.setItem(tokenKey, tokenFromUrl);
            this.joinTokens[this.principalId] = tokenFromUrl;
            params.delete('join_token');
            params.delete('invite_token');
            const clean = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ''}`;
            window.history.replaceState({}, '', clean);
        }
        this.isGM = this.isAuthenticatedGM();
        this.updatePrincipalIdentityUI();
        this.updateDmControls();
        console.log('Principal context set:', this.principalId, defaultMember.display_name);
    },

    async selectPrincipal(principalId) {
        if (!principalId) return;
        if (!this.isGM && principalId !== this.principalId) {
            console.warn('Ignoring non-GM principal switch attempt');
            this.updatePrincipalIdentityUI();
            return;
        }
        if (this.isGM) {
            this.viewedPrincipalId = principalId === this.principalId ? null : principalId;
        } else {
            this.viewedPrincipalId = null;
        }
        this.updatePrincipalIdentityUI();
        this.playerState = null;
        this.lastEventSequence = null;
        this.seenEventIds = new Set();
        await this.loadPlayerStateSnapshot();
        this.renderEntityList();
        this.joinRealtimeRooms();
    },

    async loadPlayerStateSnapshot(options = {}) {
        if (!this.sessionId || !this.principalId) return false;
        try {
            const params = this.authQueryString();
            if (this.isGM && this.viewedPrincipalId) params.set('as_principal_id', this.viewedPrincipalId);
            const resp = await fetch(`/api/sessions/${this.sessionId}/player_state?${params.toString()}`);
            if (!resp.ok) return false;
            const data = await resp.json();
            if (!data.ok || !data.player_state) return false;

            this.playerState = data.player_state;
            this.isGM = this.isAuthenticatedGM();
            this.updatePrincipalIdentityUI();
            this.updateDmControls();
            window.__TTDM_PLAYER_STATE_LOADED = true;
            this.lastEventSequence = this.playerState.visible_world?.event_cursor?.last_sequence ?? null;
            this.seenEventIds = new Set();
            this.controlledEntities = (this.playerState.controlled_entities || []).map(e => e.entity_id);
            this.entities = this.playerState.visible_world?.visible_entities || this.entities;
            this.storyState = {
                current_location: this.playerState.narrative_state?.location,
                game_time: this.playerState.narrative_state?.game_time,
                active_npcs: this.playerState.narrative_state?.known_active_npcs || [],
                active_quests: this.playerState.narrative_state?.known_active_quests || [],
                plot_threads: this.playerState.narrative_state?.known_plot_threads || [],
                party_resources: this.playerState.narrative_state?.known_party_resources || {},
            };

            const selectedId = this.playerState.ui_state?.selected_entity_id;
            if (selectedId) this.selectedEntity = this.entities.find(e => e.id === selectedId) || null;

            const recent = this.playerState.visible_world?.visible_recent_events || [];
            if (recent.length > 0) {
                this.addEvent({type: 'SYSTEM', payload: {message: `--- Player state restored: ${recent.length} visible events loaded ---`}});
                for (const event of recent) {
                    if (event.event_id) this.seenEventIds.add(String(event.event_id));
                    this.addHistoryEvent(event);
                }
            }

            this.updateStoryStateUI();
            this.renderEntityList();
            if (this._mapRenderer && this.mapContext) {
                this._mapRenderer.setEntities(this.entities, this.controlledEntities);
                this._refreshDiscoveredPOIs();
            }
            this._updateCombatHUD();
            return true;
        } catch (e) {
            const transientFetchFailure = e instanceof TypeError && String(e.message || e).includes('Failed to fetch');
            if (options.silentTransient && transientFetchFailure) {
                console.warn('Player state snapshot refresh skipped after transient fetch failure:', e);
            } else {
                console.error('Failed to load player state snapshot:', e);
            }
            return false;
        }
    },

    joinRealtimeRooms() {
        if (!this.socket || !this.connected || !this.campaign || !this.principalId) return;
        this.socket.emit('join_campaign', {
            campaign_id: this.campaign.id,
            session_id: this.sessionId,
            principal_id: this.principalId,
            join_token: this.localJoinTokenFor(this.authenticatedMember()),
        });
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

    escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, ch => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;',
        }[ch]));
    },

    formatPayloadSummary(type, payload, data = {}) {
        const safeType = String(type || '').toLowerCase();
        if (!payload || typeof payload !== 'object') return this.escapeHtml(payload || '');
        if (payload.message || payload.narration || payload.dialogue) {
            return this.escapeHtml(payload.message || payload.narration || payload.dialogue);
        }
        if (payload.summary) return this.escapeHtml(payload.summary);
        if (payload.tool_name) {
            const tool = String(payload.tool_name).replace(/_/g, ' ');
            const result = payload.result;
            if (typeof result === 'string') return `<strong>${this.escapeHtml(tool)}</strong><div style="margin-top:4px;font-size:12px;color:var(--text-secondary)">${this.escapeHtml(result).substring(0, 240)}</div>`;
            return `<strong>${this.escapeHtml(tool)}</strong>`;
        }
        const delta = payload.delta || payload.state_delta || payload;
        const actionType = payload.action_type || data.action_type || delta.action_type;
        if (actionType) return this.escapeHtml(String(actionType).replace(/_/g, ' ').toLowerCase());
        if (delta.entity_id && (delta.x !== undefined || delta.y !== undefined)) {
            return this.escapeHtml(`Entity moved to (${delta.x ?? '?'}, ${delta.y ?? '?'})`);
        }
        if (safeType === 'state_delta' || safeType === 'tool_call' || payload.deltas || payload.changes) {
            return 'Game state updated.';
        }
        return 'Game event received.';
    },

    addHistoryEvent(data) {
        // Add a historical event (with original timestamp)
        const feed = document.getElementById('eventFeed');
        const type = (data.event_type || data.type || 'system').toLowerCase();
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
            content += this.formatPayloadSummary(type, payload, data);
        } else if (type === 'dialogue' || type === 'chat') {
            const speaker = data.speaker_name || payload.speaker || 'Unknown';
            const msg = payload.dialogue || payload.message || '';
            content += `<span class="speaker">${this.escapeHtml(speaker)}:</span> ${this.escapeHtml(msg)}`;
        } else if (type === 'action') {
            content += `<strong>${this.escapeHtml(payload.action_type || 'Action')}</strong>`;
            if (payload.result) {
                const res = typeof payload.result === 'string' ? payload.result : this.formatPayloadSummary(type, payload.result, data);
                content += `<div style="margin-top:4px;font-size:12px;color:var(--text-secondary)">${this.escapeHtml(res).substring(0, 200)}</div>`;
            }
        } else {
            content += this.formatPayloadSummary(type, payload, data);
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
            const label = enc.name || `Encounter ${String(enc.id || '').slice(0, 8)}`;
            sel.innerHTML += `<option value="${enc.id}" ${this.selectedEncounter?.id === enc.id ? 'selected' : ''}>${this.escapeHtml(label)} (${this.escapeHtml(enc.status || '')})</option>`;
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
        if (this._shouldRefetchSnapshotForEvent(data)) return;
        const feed = document.getElementById('eventFeed');
        const type = (data.type || data.event_type || 'system').toLowerCase();
        const payload = data.payload || data;

        const item = document.createElement('div');
        item.className = `event-item ${type}`;

        const now = new Date().toLocaleTimeString('en-US', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'});
        let content = `<span class="timestamp">${now}</span>`;

        if (type === 'narration') {
            content += this.formatPayloadSummary(type, payload, data);
        } else if (type === 'dialogue' || type === 'chat') {
            const speaker = payload.speaker || 'Unknown';
            const msg = payload.dialogue || payload.message || '';
            content += `<span class="speaker">${this.escapeHtml(speaker)}:</span> ${this.escapeHtml(msg)}`;
        } else if (type === 'tool_call') {
            const tool = payload.tool_name || 'action';
            content += `<strong>${this.escapeHtml(tool.replace(/_/g, ' '))}</strong>`;
            if (payload.rolls) {
                for (const r of payload.rolls) {
                    content += `<div class="roll-result">${this.escapeHtml(r.breakdown || 'Roll resolved')}</div>`;
                }
            }
            if (payload.result) {
                const res = typeof payload.result === 'string'
                    ? payload.result
                    : this.formatPayloadSummary(type, payload.result, data);
                content += `<div style="margin-top:4px;font-size:12px;color:var(--text-secondary)">${this.escapeHtml(res).substring(0, 200)}</div>`;
            }
        } else if (type === 'error') {
            item.classList.add('error');
            content += this.escapeHtml(payload.message || payload.error || 'Error');
        } else {
            content += this.formatPayloadSummary(type, payload, data);
        }

        item.innerHTML = content;
        feed.appendChild(item);
        feed.scrollTop = feed.scrollHeight;

        this.events.push(data);
    },

    _eventSequence(data) {
        const seq = data?.seq_id ?? data?.sequence ?? data?.ledger_seq_id ?? data?.payload?.seq_id;
        if (seq === undefined || seq === null || seq === '') return null;
        const parsed = Number(seq);
        return Number.isFinite(parsed) ? parsed : null;
    },

    _eventId(data) {
        return data?.event_id || data?.payload?.event_id || null;
    },

    _shouldRefetchSnapshotForEvent(data) {
        const eventType = String(data?.event_type || data?.type || '').toLowerCase();
        const payload = data?.payload || {};
        if (
            eventType.includes('control')
            || payload.control_version !== undefined
            || payload.controller_principal_id !== undefined
        ) {
            this.loadPlayerStateSnapshot();
        }

        const eventId = this._eventId(data);
        if (eventId && this.seenEventIds.has(String(eventId))) return true;

        const seq = this._eventSequence(data);
        if (seq !== null) {
            if (this.lastEventSequence !== null && seq <= this.lastEventSequence) {
                if (eventId) this.seenEventIds.add(String(eventId));
                return true;
            }
            if (this.lastEventSequence !== null && seq > this.lastEventSequence + 1) {
                this.addEvent({type: 'SYSTEM', payload: {message: 'Event stream gap detected. Refreshing player state...'}});
                this.loadPlayerStateSnapshot();
                return true;
            }
            this.lastEventSequence = seq;
        }
        if (eventId) this.seenEventIds.add(String(eventId));
        return false;
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
                    const label = data.active_entity_name || data.current_entity_name || data.current_turn_order || 'next actor';
                    this.addEvent({type: 'SYSTEM', payload: {message: `Turn advanced to ${label}`}});
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
                    body: JSON.stringify({
                        campaign_id: this.campaign?.id,
                        session_id: this.sessionId,
                        event_data: {campaign_id: this.campaign?.id, campaign: this.campaign?.name},
                        context: text,
                    }),
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
            const resp = await fetch(`/api/encounters/${this.selectedEncounter.id}/advance?${this.authQueryString().toString()}`, {method: 'POST'});
            const data = await resp.json();
            if (!resp.ok || data.error) {
                this.addEvent({type: 'ERROR', payload: {message: data.error || 'Advance initiative failed'}});
                return;
            }
            const label = data.active_entity_name || data.current_entity_name || data.current_turn_order || 'next actor';
            this.addEvent({type: 'SYSTEM', payload: {message: `Turn advanced to ${label}`}});
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
            const resp = await fetch(`/api/narrate?${this.authQueryString().toString()}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    campaign_id: this.campaign?.id,
                    session_id: this.sessionId,
                    event_data: {campaign_id: this.campaign?.id, campaign: this.campaign?.name},
                    context: 'Describe the current scene in the campaign.',
                }),
            });
            const data = await resp.json();
            if (!resp.ok || data.error) {
                this.addEvent({type: 'ERROR', payload: {message: data.error || 'Narration failed'}});
                return;
            }
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
        // If nothing selected but the player can move a PC on the board,
        // auto-select it (covers GM mode where controlledEntities is empty).
        if (!this.selectedEntity) {
            const pc = (this.entities || []).find(e =>
                e.entity_type === 'PC'
                && e.public_sheet?.x !== undefined
                && this.canControl(e.id)
            );
            if (pc) this.selectedEntity = pc;
        }
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
        // Default movement target = the player's controlled PC, OR if the
        // local player is the GM (no entity directly tied to them), the
        // currently-selected entity, OR the first PC on the map.
        let own = (this.entities || []).find(e =>
            this.controlledEntities?.includes(e.id) && e.public_sheet?.x !== undefined
        );
        if (!own && this.selectedEntity && this.canControl(this.selectedEntity.id)
                 && this.selectedEntity.public_sheet?.x !== undefined) {
            own = this.selectedEntity;
        }
        if (!own) {
            // Last resort: GM gets to push the first PC on the map.
            own = (this.entities || []).find(e =>
                e.entity_type === 'PC' && e.public_sheet?.x !== undefined && this.canControl(e.id)
            );
        }
        if (!own) return;
        // Make subsequent WASDs continue from the same actor.
        this.selectedEntity = own;
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
            r.setEntities(showEntities ? (this.entities || []) : [], this.controlledEntities);
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
            this._refreshDecorations(mapId);
        } catch (e) {
            console.error('Map render error:', e);
        }
    },

    async _refreshDecorations(mapId) {
        if (!this._mapRenderer) return;
        try {
            const r = await fetch(`/api/maps/${mapId}/decorations`);
            if (!r.ok) return;
            const decos = await r.json();
            this._mapRenderer.setDecorations(decos);
        } catch (e) {
            console.error('Decorations fetch failed:', e);
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

    async startEncounter() {
        if (!this.campaign || !this.sessionId) {
            this.addEvent({type: 'ERROR', payload: {message: 'No active campaign/session'}});
            return;
        }
        try {
            const entityIds = (this.entities || [])
                .filter(e => ['PC', 'NPC', 'MONSTER'].includes(e.entity_type) && e.status !== 'INACTIVE')
                .slice(0, 12)
                .map(e => e.id);
            const resp = await fetch(`/api/campaigns/${this.campaign.id}/encounters?${this.authQueryString().toString()}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({session_id: this.sessionId, entity_ids: entityIds}),
            });
            const data = await resp.json();
            if (!resp.ok || data.error) {
                this.addEvent({type: 'ERROR', payload: {message: data.error || 'Encounter creation failed'}});
                return;
            }
            this.addEvent({type: 'SYSTEM', payload: {message: 'Encounter started.'}});
            await this.loadEncounters();
        } catch (e) {
            this.addEvent({type: 'ERROR', payload: {message: e.message}});
        }
    },
};

window.App = App;
document.addEventListener('DOMContentLoaded', () => App.init());

export { App };
