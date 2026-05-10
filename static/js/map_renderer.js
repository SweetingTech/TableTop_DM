// PS1-era map renderer for TableTop_DM.
// Orthographic camera, NearestFilter textures, no antialiasing.
// Phase 1: tile floor + entity sprites + orbit pan/zoom.
// Later phases add hierarchy navigation, click-to-move, WASD, POIs, combat HUD.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// Saturated FF-Tactics-ish palette: each terrain type has its own hue family
// and is bright enough to read at small zoom. Walls are 3D boxes (see below).
const TERRAIN_COLORS = {
    stone_floor: 0x6b6e85,
    grass:       0x4d8a3a,
    dirt:        0x8a5a35,
    water:       0x2a6fb0,
    sand:        0xd4b56a,
    wood:        0xa3702c,
    wall:        0x222226,
};
const TILE_GRID_LINE = 0x1a1a26;
const WALL_OUTLINE   = 0x000000;

// Pixel-art textures for each terrain. We bake a 32×32 canvas per type with
// deterministic noise so grass actually looks like grass, water like water,
// etc. NearestFilter keeps the pixels crisp at any zoom.
function _terrainCanvas(type) {
    const c = document.createElement('canvas');
    c.width = c.height = 32;
    const ctx = c.getContext('2d');
    // deterministic pseudo-random so each type is identical across all tiles
    let seed = type.split('').reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) | 0, 7);
    const rnd = () => { seed = (seed * 1664525 + 1013904223) | 0; return ((seed >>> 0) / 0xffffffff); };

    const base = TERRAIN_COLORS[type] ?? 0x444;
    const r = (base >> 16) & 0xff, g = (base >> 8) & 0xff, b = base & 0xff;
    const tone = (dr, dg, db, a = 1) =>
        `rgba(${Math.max(0, Math.min(255, r + dr))},${Math.max(0, Math.min(255, g + dg))},${Math.max(0, Math.min(255, b + db))},${a})`;

    // base fill
    ctx.fillStyle = `rgb(${r},${g},${b})`;
    ctx.fillRect(0, 0, 32, 32);

    if (type === 'grass') {
        // sprigs of darker / lighter green
        for (let i = 0; i < 60; i++) {
            const x = Math.floor(rnd() * 32), y = Math.floor(rnd() * 32);
            ctx.fillStyle = rnd() > 0.5 ? tone(-30, -20, -30) : tone(20, 30, 10);
            ctx.fillRect(x, y, 1, 2); // tiny vertical blade
        }
    } else if (type === 'water') {
        // horizontal ripple highlights
        for (let i = 0; i < 14; i++) {
            const y = Math.floor(rnd() * 32);
            const w = 4 + Math.floor(rnd() * 10);
            const x = Math.floor(rnd() * (32 - w));
            ctx.fillStyle = tone(40, 50, 60, 0.6);
            ctx.fillRect(x, y, w, 1);
        }
    } else if (type === 'stone_floor') {
        // crack lines + a few darker speckles
        for (let i = 0; i < 4; i++) {
            ctx.strokeStyle = tone(-30, -30, -25, 0.7);
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(Math.floor(rnd() * 32), Math.floor(rnd() * 32));
            ctx.lineTo(Math.floor(rnd() * 32), Math.floor(rnd() * 32));
            ctx.stroke();
        }
        for (let i = 0; i < 30; i++) {
            ctx.fillStyle = tone(rnd() > 0.5 ? 20 : -25, rnd() > 0.5 ? 20 : -25, rnd() > 0.5 ? 25 : -20);
            ctx.fillRect(Math.floor(rnd() * 32), Math.floor(rnd() * 32), 1, 1);
        }
    } else if (type === 'sand') {
        // fine grainy dots
        for (let i = 0; i < 80; i++) {
            ctx.fillStyle = tone(rnd() > 0.5 ? 25 : -30, rnd() > 0.5 ? 25 : -30, rnd() > 0.5 ? 15 : -25);
            ctx.fillRect(Math.floor(rnd() * 32), Math.floor(rnd() * 32), 1, 1);
        }
    } else if (type === 'dirt') {
        // pebbles + scuffs
        for (let i = 0; i < 24; i++) {
            ctx.fillStyle = tone(rnd() > 0.5 ? -30 : 25, rnd() > 0.5 ? -25 : 20, rnd() > 0.5 ? -20 : 15);
            const s = rnd() > 0.85 ? 2 : 1;
            ctx.fillRect(Math.floor(rnd() * 32), Math.floor(rnd() * 32), s, s);
        }
    } else if (type === 'wood') {
        // horizontal grain stripes
        for (let i = 0; i < 32; i += 3) {
            ctx.fillStyle = tone(-20, -15, -10, 0.55);
            ctx.fillRect(0, i, 32, 1);
        }
        for (let i = 0; i < 8; i++) {
            ctx.fillStyle = tone(20, 15, 10, 0.6);
            ctx.fillRect(Math.floor(rnd() * 32), Math.floor(rnd() * 32), 2, 1);
        }
    }

    // edge bevel — light top-left, dark bottom-right — gives every tile depth
    ctx.fillStyle = 'rgba(255,255,255,0.18)';
    ctx.fillRect(0, 0, 32, 1);
    ctx.fillRect(0, 0, 1, 32);
    ctx.fillStyle = 'rgba(0,0,0,0.30)';
    ctx.fillRect(0, 31, 32, 1);
    ctx.fillRect(31, 0, 1, 32);

    return c;
}
const ENTITY_COLORS = { PC: 0x4caf50, NPC: 0x42a5f5, MONSTER: 0xff4444, GOD: 0xce93d8 };
const POI_GLYPHS = {
    NPC:      { glyph: '☻', color: 0x9ad7ff },
    BUILDING: { glyph: '⌂', color: 0xffd54f },
    SIGN:     { glyph: '!', color: 0xffe28a },
    HAZARD:   { glyph: '⚠', color: 0xff7043 },
    TREASURE: { glyph: '$', color: 0xffd700 },
    PORTAL:   { glyph: '◉', color: 0xb39ddb },
    GENERIC:  { glyph: '•', color: 0xcccccc },
};
const VIEW_SIZE = 14; // tiles visible vertically at zoom 1

class MapRenderer {
    constructor(canvas) {
        this.canvas = canvas;
        this.tiles = [];
        this.entitySprites = new Map();
        this.poiSprites = new Map();
        this.mapData = null;
        this._spriteCache = new Map();
        this._poiTexCache = new Map();
        this._terrainMatCache = new Map(); // material per terrain type

        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x0a0a1a);

        this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'low-power' });
        this.renderer.setPixelRatio(window.devicePixelRatio);

        const w = canvas.clientWidth || 800;
        const h = canvas.clientHeight || 600;
        const aspect = w / h;
        this.camera = new THREE.OrthographicCamera(
            -VIEW_SIZE * aspect / 2, VIEW_SIZE * aspect / 2,
            VIEW_SIZE / 2, -VIEW_SIZE / 2,
            0.1, 1000,
        );
        // Isometric-ish tilt: ~50° down from horizontal. Wall side-faces show,
        // so 3D blocks read as actual obstacles. FF Tactics canonical angle.
        this.camera.position.set(0, 18, 14);
        this.camera.lookAt(0, 0, 0);

        this.controls = new OrbitControls(this.camera, canvas);
        this.controls.enableRotate = false;
        this.controls.enableDamping = false;
        this.controls.screenSpacePanning = true;
        this.controls.zoomToCursor = true;
        this.controls.minZoom = 0.4;
        this.controls.maxZoom = 4.0;
        this.controls.mouseButtons = {
            LEFT: null, // reserved for click-to-move (Phase 3)
            MIDDLE: THREE.MOUSE.DOLLY,
            RIGHT: THREE.MOUSE.PAN,
        };

        // Render on demand — we don't need 60Hz for a tactical map.
        // Re-render fires when: controls change, map/entities update, resize.
        this._render = () => this.renderer.render(this.scene, this.camera);
        this.controls.addEventListener('change', this._render);

        // Phase 3 input: raycaster click-to-move + WASD step.
        // Renderer just translates raw input → tile coords and emits via
        // onTileClick / onTileStep callbacks. The app layer is the policy.
        this._raycaster = new THREE.Raycaster();
        this._pointer = new THREE.Vector2();
        this._groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
        this.onTileClick = null;     // (gridX, gridY) => void
        this.onTileStep = null;      // (dx, dy) => void   dx,dy in {-1,0,1}
        this._installInputHandlers();

        this._handleResize();
        this._resizeObserver = new ResizeObserver(() => this._handleResize());
        this._resizeObserver.observe(canvas);

        this._render();
    }

    // --------- public API ---------

    _terrainMaterial(type) {
        let mat = this._terrainMatCache.get(type);
        if (mat) return mat;
        const tex = new THREE.CanvasTexture(_terrainCanvas(type));
        tex.minFilter = THREE.NearestFilter;
        tex.magFilter = THREE.NearestFilter;
        tex.generateMipmaps = false;
        mat = new THREE.MeshBasicMaterial({ map: tex, side: THREE.DoubleSide });
        this._terrainMatCache.set(type, mat);
        return mat;
    }

    /** Load a map and its nodes (terrain). Pass null to clear. */
    loadMap(mapData, nodes) {
        this._clearTiles();
        this.mapData = mapData;
        if (!mapData || !nodes) return;

        // Floor tiles are full 1.0 because their texture's edge bevel does
        // the visual separating. Walls are 3D boxes so they actually stand up.
        const tileGeo = new THREE.PlaneGeometry(1.0, 1.0);
        const wallGeo = new THREE.BoxGeometry(0.95, 0.7, 0.95);

        // Underlay = grid-line color so any gap reads as a dark line.
        const underlay = new THREE.Mesh(
            new THREE.PlaneGeometry(mapData.width, mapData.height),
            new THREE.MeshBasicMaterial({ color: TILE_GRID_LINE, side: THREE.DoubleSide }),
        );
        underlay.rotation.x = -Math.PI / 2;
        underlay.position.set(0, -0.02, 0);
        this.scene.add(underlay);
        this.tiles.push(underlay);

        for (const node of nodes) {
            const terrain = node.terrain || {};
            const isWall = node.collision_mask && node.collision_mask[0] === '1';
            const [wx, wz] = this._gridToWorld(node.x, node.y);

            if (isWall) {
                // 3D wall block — stands ~0.7 units tall, dark face all around.
                const wallMat = new THREE.MeshBasicMaterial({ color: TERRAIN_COLORS.wall });
                const wall = new THREE.Mesh(wallGeo, wallMat);
                wall.position.set(wx, 0.35, wz);
                this.scene.add(wall);
                this.tiles.push(wall);
                // outline edge for definition at any zoom
                const edges = new THREE.LineSegments(
                    new THREE.EdgesGeometry(wallGeo),
                    new THREE.LineBasicMaterial({ color: WALL_OUTLINE }),
                );
                edges.position.copy(wall.position);
                this.scene.add(edges);
                this.tiles.push(edges);
            } else {
                const mat = this._terrainMaterial(terrain.type || 'stone_floor');
                const mesh = new THREE.Mesh(tileGeo, mat);
                mesh.rotation.x = -Math.PI / 2;
                mesh.position.set(wx, 0, wz);
                this.scene.add(mesh);
                this.tiles.push(mesh);
                if (terrain.difficult) {
                    const tintMat = new THREE.MeshBasicMaterial({
                        color: 0xff7a00, transparent: true, opacity: 0.32, side: THREE.DoubleSide,
                    });
                    const tint = new THREE.Mesh(tileGeo, tintMat);
                    tint.rotation.x = -Math.PI / 2;
                    tint.position.set(wx, 0.002, wz);
                    this.scene.add(tint);
                    this.tiles.push(tint);
                }
            }
        }
        this._fitCameraToMap();
        this._render();
    }

    /** Render entity sprites at their public_sheet (x, y) positions. */
    setEntities(entities) {
        const seen = new Set();
        for (const e of entities) {
            if (e.entity_type === 'LOCATION') continue;
            const sheet = e.public_sheet || {};
            if (sheet.x === undefined || sheet.y === undefined) continue;
            seen.add(e.id);
            let sprite = this.entitySprites.get(e.id);
            if (!sprite) {
                sprite = this._buildSprite(e);
                this.scene.add(sprite);
                this.entitySprites.set(e.id, sprite);
            }
            const [wx, wz] = this._gridToWorld(sheet.x, sheet.y);
            sprite.position.set(wx, 0.5, wz);
        }
        // Remove sprites for entities that disappeared
        for (const [id, sprite] of this.entitySprites) {
            if (!seen.has(id)) {
                this.scene.remove(sprite);
                sprite.material.dispose();
                this.entitySprites.delete(id);
            }
        }
        this._render();
    }

    /** Replace the visible POI set. Pass [] to clear. */
    setPOIs(pois) {
        const seen = new Set();
        for (const p of pois || []) {
            seen.add(p.id);
            let sprite = this.poiSprites.get(p.id);
            if (!sprite) {
                sprite = this._buildPOI(p);
                this.scene.add(sprite);
                this.poiSprites.set(p.id, sprite);
            }
            const [wx, wz] = this._gridToWorld(p.x, p.y);
            sprite.position.set(wx, 0.4, wz);
        }
        for (const [id, sprite] of this.poiSprites) {
            if (!seen.has(id)) {
                this.scene.remove(sprite);
                sprite.material.dispose();
                this.poiSprites.delete(id);
            }
        }
        this._render();
    }

    /** Center the camera on a grid coordinate. */
    focusOn(gridX, gridY) {
        if (!this.mapData) return;
        const [wx, wz] = this._gridToWorld(gridX, gridY);
        this.controls.target.set(wx, 0, wz);
        // Match constructor angle: 18 up, 14 toward camera-front for ~50° tilt
        this.camera.position.set(wx, 18, wz + 14);
        this.controls.update();
        this._render();
    }

    /** Tear down (used when navigating away or reloading). */
    dispose() {
        this._resizeObserver.disconnect();
        this.controls.removeEventListener('change', this._render);
        this.canvas.removeEventListener('pointerdown', this._onPointerDown);
        this.canvas.removeEventListener('pointermove', this._onPointerMove);
        this.canvas.removeEventListener('click', this._onClick);
        window.removeEventListener('keydown', this._onKey);
        this._clearTiles();
        for (const sprite of this.entitySprites.values()) {
            this.scene.remove(sprite);
            sprite.material.dispose();
        }
        this.entitySprites.clear();
        for (const sprite of this.poiSprites.values()) {
            this.scene.remove(sprite);
            sprite.material.dispose();
        }
        this.poiSprites.clear();
        this.controls.dispose();
        this.renderer.dispose();
    }

    // --------- internals ---------

    _gridToWorld(gx, gy) {
        const w = this.mapData?.width || 20;
        const h = this.mapData?.height || 20;
        // Center the map at the world origin. +X = east, +Z = south.
        return [gx - w / 2 + 0.5, gy - h / 2 + 0.5];
    }

    _clearTiles() {
        for (const t of this.tiles) {
            this.scene.remove(t);
            t.geometry?.dispose();
            t.material?.dispose();
        }
        this.tiles = [];
    }

    _buildPOI(poi) {
        // If the POI has its own image (uploaded or AI-generated), use it.
        // Otherwise fall back to a glyph based on `kind`.
        if (poi.image_url) {
            const tex = new THREE.TextureLoader().load(poi.image_url, () => this._render());
            tex.minFilter = THREE.NearestFilter;
            tex.magFilter = THREE.NearestFilter;
            tex.generateMipmaps = false;
            const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true });
            const sprite = new THREE.Sprite(mat);
            sprite.scale.set(0.85, 0.85, 1);
            sprite.userData = { poi };
            return sprite;
        }
        const def = POI_GLYPHS[poi.kind] || POI_GLYPHS.GENERIC;
        const key = `${def.glyph}|${def.color}`;
        let tex = this._poiTexCache.get(key);
        if (!tex) {
            tex = this._makePOITexture(def.glyph, def.color);
            this._poiTexCache.set(key, tex);
        }
        const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true });
        const sprite = new THREE.Sprite(mat);
        sprite.scale.set(0.7, 0.7, 1);
        sprite.userData = { poi };
        return sprite;
    }

    _makePOITexture(glyph, hexColor) {
        const c = document.createElement('canvas');
        c.width = c.height = 48;
        const ctx = c.getContext('2d');
        // Translucent halo so the glyph reads against any tile color
        ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
        ctx.beginPath();
        ctx.arc(24, 24, 22, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#' + hexColor.toString(16).padStart(6, '0');
        ctx.font = 'bold 24px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(glyph, 24, 25);
        const tex = new THREE.CanvasTexture(c);
        tex.minFilter = THREE.NearestFilter;
        tex.magFilter = THREE.NearestFilter;
        tex.generateMipmaps = false;
        return tex;
    }

    _buildSprite(entity) {
        const letter = (entity.name || '?')[0].toUpperCase();
        const color = ENTITY_COLORS[entity.entity_type] || 0x888888;
        const key = `${letter}|${color.toString(16)}`;
        let tex = this._spriteCache.get(key);
        if (!tex) {
            tex = this._makeLabelTexture(letter, color);
            this._spriteCache.set(key, tex);
        }
        const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true });
        const sprite = new THREE.Sprite(mat);
        // Slightly larger than a tile so the token visibly stands ON the floor.
        sprite.scale.set(1.05, 1.05, 1);
        return sprite;
    }

    _makeLabelTexture(letter, hexColor) {
        const c = document.createElement('canvas');
        c.width = c.height = 96;
        const ctx = c.getContext('2d');
        // outer black halo so the token reads against any tile color
        ctx.fillStyle = 'rgba(0,0,0,0.85)';
        ctx.beginPath();
        ctx.arc(48, 48, 44, 0, Math.PI * 2);
        ctx.fill();
        // colored disc body (4px inset from halo)
        ctx.fillStyle = '#' + hexColor.toString(16).padStart(6, '0');
        ctx.beginPath();
        ctx.arc(48, 48, 40, 0, Math.PI * 2);
        ctx.fill();
        // bright inner ring for definition
        ctx.strokeStyle = 'rgba(255,255,255,0.65)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(48, 48, 38, 0, Math.PI * 2);
        ctx.stroke();
        // letter — black outline + white fill so it reads on any disc color
        ctx.font = 'bold 54px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.lineWidth = 5;
        ctx.strokeStyle = 'rgba(0,0,0,0.9)';
        ctx.strokeText(letter, 48, 50);
        ctx.fillStyle = 'white';
        ctx.fillText(letter, 48, 50);
        const tex = new THREE.CanvasTexture(c);
        tex.minFilter = THREE.NearestFilter;
        tex.magFilter = THREE.NearestFilter;
        tex.generateMipmaps = false;
        return tex;
    }

    _handleResize() {
        const w = this.canvas.clientWidth;
        const h = this.canvas.clientHeight;
        if (w === 0 || h === 0) return;
        const aspect = w / h;
        this.camera.left = -VIEW_SIZE * aspect / 2;
        this.camera.right = VIEW_SIZE * aspect / 2;
        this.camera.top = VIEW_SIZE / 2;
        this.camera.bottom = -VIEW_SIZE / 2;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(w, h, false);
        this._render?.();
    }

    _fitCameraToMap() {
        if (!this.mapData) return;
        // Center on map midpoint, leave zoom alone so user pan/zoom is preserved.
        const cx = this.mapData.width / 2;
        const cy = this.mapData.height / 2;
        // Only reset target on first load
        if (!this._cameraInitialized) {
            this.focusOn(cx, cy);
            this._cameraInitialized = true;
        }
    }

    _installInputHandlers() {
        // Track drag distance so a click that moved more than a few pixels is
        // treated as a pan, not a tile click.
        this._dragStart = null;
        this._dragDistance = 0;
        this._onPointerDown = (e) => {
            if (e.button !== 0) return;
            this._dragStart = { x: e.clientX, y: e.clientY };
            this._dragDistance = 0;
        };
        this._onPointerMove = (e) => {
            if (!this._dragStart) return;
            const dx = e.clientX - this._dragStart.x;
            const dy = e.clientY - this._dragStart.y;
            this._dragDistance = Math.hypot(dx, dy);
        };
        this._onClick = (e) => {
            if (this._dragDistance > 5) return; // it was a drag, not a click
            if (!this.mapData) return;
            const rect = this.canvas.getBoundingClientRect();
            this._pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
            this._pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
            this._raycaster.setFromCamera(this._pointer, this.camera);

            // Test for POI hits first — POI sprites take priority over tile-click
            // because they're clickable drilldown markers on World/Area tiers.
            if (this.poiSprites.size && this.onPOIClick) {
                const intersects = this._raycaster.intersectObjects([...this.poiSprites.values()], false);
                if (intersects.length) {
                    const sprite = intersects[0].object;
                    const poi = sprite.userData?.poi;
                    if (poi) {
                        this.onPOIClick(poi);
                        return;
                    }
                }
            }
            if (!this.onTileClick) return;
            const hit = new THREE.Vector3();
            if (!this._raycaster.ray.intersectPlane(this._groundPlane, hit)) return;
            const [gx, gy] = this._worldToGrid(hit.x, hit.z);
            if (gx < 0 || gx >= this.mapData.width || gy < 0 || gy >= this.mapData.height) return;
            this.onTileClick(gx, gy);
        };
        this.canvas.addEventListener('pointerdown', this._onPointerDown);
        this.canvas.addEventListener('pointermove', this._onPointerMove);
        this.canvas.addEventListener('click', this._onClick);

        // WASD step. Skipped if user is typing in an input or the tab is hidden.
        this._onKey = (e) => {
            if (!this.onTileStep) return;
            const tag = (document.activeElement?.tagName || '').toUpperCase();
            if (tag === 'INPUT' || tag === 'TEXTAREA' || document.activeElement?.isContentEditable) return;
            if (this.canvas.offsetParent === null) return; // map tab not visible
            let dx = 0, dy = 0;
            const k = e.key.toLowerCase();
            if (k === 'w' || e.key === 'ArrowUp') dy = -1;
            else if (k === 's' || e.key === 'ArrowDown') dy = 1;
            else if (k === 'a' || e.key === 'ArrowLeft') dx = -1;
            else if (k === 'd' || e.key === 'ArrowRight') dx = 1;
            else return;
            e.preventDefault();
            this.onTileStep(dx, dy);
        };
        window.addEventListener('keydown', this._onKey);
    }

    _worldToGrid(wx, wz) {
        const w = this.mapData?.width || 20;
        const h = this.mapData?.height || 20;
        return [Math.floor(wx + w / 2), Math.floor(wz + h / 2)];
    }
}

window.MapRenderer = MapRenderer;
