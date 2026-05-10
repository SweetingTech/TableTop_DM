import os
import uuid
import json
import traceback
import socket
import hashlib
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib import request as urllib_request, error as urllib_error
from flask import Flask, render_template, request, jsonify, Response
from flask_socketio import SocketIO, emit, join_room, leave_room
import psycopg2
import psycopg2.extras
from werkzeug.utils import secure_filename

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", os.urandom(32).hex())
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

REDIS_DEFAULT_HOST = "localhost"
REDIS_DEFAULT_PORT = 6379
QDRANT_DEFAULT_HOST = "localhost"
QDRANT_DEFAULT_HTTP_PORT = 6333
RAG_CHUNK_SIZE = 1000
RAG_CHUNK_OVERLAP = 150
RAG_WORKERS = int(os.environ.get("RAG_WORKERS", "2"))
RAG_EXECUTOR = ThreadPoolExecutor(max_workers=max(1, RAG_WORKERS))


def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])


@app.after_request
def add_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.route("/")
def index():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(
        "SELECT * FROM state.campaigns "
        "WHERE status NOT IN ('PURGED', 'TOMBSTONED') "
        "ORDER BY created_at DESC"
    )
    campaigns = cur.fetchall()

    cur.execute("SELECT * FROM state.principals ORDER BY display_name")
    principals = cur.fetchall()

    cur.execute("""
        SELECT e.*, p.display_name as controller_name
        FROM state.entities e
        LEFT JOIN state.principals p ON e.controller_principal_id = p.id
        ORDER BY e.entity_type, e.name
    """)
    entities = cur.fetchall()

    cur.execute("""
        SELECT enc.*, c.name as campaign_name
        FROM state.encounters enc
        JOIN state.campaigns c ON enc.campaign_id = c.id
        ORDER BY enc.created_at DESC
    """)
    encounters = cur.fetchall()

    cur.execute("""
        SELECT es.*, e.name as entity_name
        FROM state.encounter_slots es
        JOIN state.entities e ON es.entity_id = e.id
        ORDER BY es.turn_order
    """)
    encounter_slots = cur.fetchall()

    cur.execute("""
        SELECT m.*, c.name as campaign_name
        FROM state.maps m
        JOIN state.campaigns c ON m.campaign_id = c.id
    """)
    maps = cur.fetchall()

    cur.execute("""
        SELECT cm.*, p.display_name, p.principal_type, c.name as campaign_name
        FROM state.campaign_members cm
        JOIN state.principals p ON cm.principal_id = p.id
        JOIN state.campaigns c ON cm.campaign_id = c.id
    """)
    members = cur.fetchall()

    cur.execute("""
        SELECT rt.*, e.name as entity_name
        FROM state.reaction_triggers rt
        JOIN state.entities e ON rt.entity_id = e.id
    """)
    triggers = cur.fetchall()

    cur.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ('state','ledger','infra_meta')
        ORDER BY table_schema, table_name
    """)
    all_tables = cur.fetchall()

    cur.execute("SELECT * FROM infra_meta.schema_migrations ORDER BY applied_at")
    migrations = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "index.html",
        campaigns=campaigns,
        principals=principals,
        entities=entities,
        encounters=encounters,
        encounter_slots=encounter_slots,
        maps=maps,
        members=members,
        triggers=triggers,
        all_tables=all_tables,
        migrations=migrations,
        json=json,
    )


@app.route("/game")
def game():
    return render_template("game.html")


@app.route("/control")
def control():
    return render_template("control.html")


@app.route("/help")
@app.route("/help/")
@app.route("/help/<path:page>")
def help_page(page="index"):
    """Serve wiki/help documentation"""
    import markdown
    from pathlib import Path

    wiki_dir = Path(__file__).parent / "docs" / "wiki"

    # Sanitize page name
    page = page.replace("..", "").strip("/")
    if not page.endswith(".md"):
        page = page + ".md"

    wiki_file = wiki_dir / page
    if not wiki_file.exists() or not str(wiki_file.resolve()).startswith(str(wiki_dir.resolve())):
        wiki_file = wiki_dir / "index.md"

    content = wiki_file.read_text(encoding="utf-8")

    # Get list of all wiki pages for navigation
    pages = []
    for f in sorted(wiki_dir.glob("*.md")):
        name = f.stem
        title = name.replace("-", " ").title()
        pages.append({"name": name, "title": title, "active": f.name == page})

    # Convert markdown to HTML
    html_content = markdown.markdown(
        content,
        extensions=["tables", "fenced_code", "toc"]
    )

    return render_template("help.html", content=html_content, pages=pages, current_page=page.replace(".md", ""))


@app.route("/health")
def health():
    return jsonify({"status": "alive"})


def _tcp_reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    """Return True when a TCP endpoint is reachable within timeout."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect((host, port))
    return True


@app.route("/readyz")
def readyz():
    """Readiness probe: verifies DB+migrations and Redis/Qdrant reachability."""
    checks = {}
    ok = True

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM infra_meta.schema_migrations")
        _ = cur.fetchone()
        cur.close()
        conn.close()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = str(exc)
        ok = False

    try:
        _tcp_reachable(
            os.environ.get("REDIS_HOST", REDIS_DEFAULT_HOST),
            int(os.environ.get("REDIS_PORT", str(REDIS_DEFAULT_PORT))),
        )
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = str(exc)
        ok = False

    try:
        qdrant_host = os.environ.get("QDRANT_HOST", QDRANT_DEFAULT_HOST)
        qdrant_port = int(
            os.environ.get("QDRANT_HTTP_PORT", str(QDRANT_DEFAULT_HTTP_PORT))
        )
        _tcp_reachable(qdrant_host, qdrant_port)
        checks["qdrant"] = "ok"
    except Exception as exc:
        checks["qdrant"] = str(exc)
        ok = False

    code = 200 if ok else 503
    return jsonify({"status": "ready" if ok else "not_ready", "checks": checks}), code


@app.route("/api/health")
def api_health():
    return readyz()


def _validate_campaign_payload(data, partial=False):
    required = [] if partial else ["name", "slug", "status", "mode"]
    for field in required:
        if not data.get(field):
            return f"{field} is required"
    if data.get("status") and data["status"] not in {
        "DRAFT",
        "ACTIVE",
        "PAUSED",
        "ENDED",
        "ARCHIVED",
        "TOMBSTONED",
        "PURGED",
    }:
        return "invalid status"
    if data.get("mode") and data["mode"] not in {
        "EXPLORATION",
        "SOCIAL",
        "COMBAT",
        "CUTSCENE",
        "PAUSED",
    }:
        return "invalid mode"
    return None


def _get_ai_config(campaign_id: str):
    from shared.db.connection import execute_one

    row = execute_one(
        "SELECT * FROM state.campaign_settings WHERE campaign_id=%s", (campaign_id,)
    )
    if row:
        return _serialize(row)
    return {
        "campaign_id": campaign_id,
        "llm_provider": "mock",
        "llm_base_url": None,
        "embedding_base_url": None,
        "dm_model": "gpt-4o-mini",
        "npc_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small",
        "settings": {},
    }


def _openai_client_for(provider: str, base_url: str | None):
    from services.llm.adapter import resolve_provider_base_url
    from openai import OpenAI

    final_base_url = resolve_provider_base_url(provider, base_url)
    api_key = os.environ.get("OPENAI_API_KEY", "dev-local")
    return OpenAI(api_key=api_key, base_url=final_base_url)


def _extract_text_chunks(storage_path: str):
    suffix = Path(storage_path).suffix.lower()
    pages: list[tuple[int, str]] = []
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(storage_path)
        for i, page in enumerate(reader.pages, 1):
            pages.append((i, page.extract_text() or ""))
    else:
        pages.append((1, Path(storage_path).read_text(encoding="utf-8", errors="ignore")))

    chunks = []
    for page_num, text in pages:
        clean = " ".join(text.split())
        if not clean:
            continue
        start = 0
        idx = 0
        while start < len(clean):
            end = min(start + RAG_CHUNK_SIZE, len(clean))
            chunk_text = clean[start:end]
            chunk_id = hashlib.sha1(f"{page_num}:{idx}:{chunk_text}".encode()).hexdigest()
            chunks.append({"chunk_id": chunk_id, "page": page_num, "text": chunk_text})
            if end >= len(clean):
                break
            start = max(end - RAG_CHUNK_OVERLAP, 0)
            idx += 1
    return chunks


def _qdrant_base_url() -> str:
    host = os.environ.get("QDRANT_HOST", QDRANT_DEFAULT_HOST)
    port = int(os.environ.get("QDRANT_HTTP_PORT", str(QDRANT_DEFAULT_HTTP_PORT)))
    return f"http://{host}:{port}"


def _qdrant_collection_name(campaign_id: str) -> str:
    return f"ttdm_{campaign_id}_rag".replace("-", "_")


def _qdrant_request(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{_qdrant_base_url()}{path}"
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib_request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Qdrant HTTP {exc.code}: {body}") from exc


def _ensure_qdrant_collection(campaign_id: str, vector_size: int) -> str:
    collection = _qdrant_collection_name(campaign_id)
    if vector_size <= 0:
        raise ValueError("vector_size must be > 0")
    try:
        _qdrant_request("GET", f"/collections/{collection}")
        return collection
    except RuntimeError:
        _qdrant_request(
            "PUT",
            f"/collections/{collection}",
            {"vectors": {"size": vector_size, "distance": "Cosine"}},
        )
        return collection


def _upsert_qdrant_points(campaign_id: str, points: list[dict], vector_size: int):
    collection = _ensure_qdrant_collection(campaign_id, vector_size)
    _qdrant_request(
        "PUT",
        f"/collections/{collection}/points",
        {"points": points},
    )


def _delete_qdrant_doc_points(campaign_id: str, doc_id: str):
    collection = _qdrant_collection_name(campaign_id)
    _qdrant_request(
        "POST",
        f"/collections/{collection}/points/delete",
        {"filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]}},
    )


def _search_qdrant(campaign_id: str, query_vector: list[float], top_k: int) -> list[dict]:
    collection = _qdrant_collection_name(campaign_id)
    response = _qdrant_request(
        "POST",
        f"/collections/{collection}/points/search",
        {"vector": query_vector, "limit": top_k, "with_payload": True},
    )
    return response.get("result", [])


def _create_entity_record(campaign_id: str, data: dict):
    from shared.db.connection import execute_one

    return execute_one(
        """
        INSERT INTO state.entities (campaign_id, entity_type, name, tags, public_sheet, secret_sheet, hp_current, hp_max, ac, speed, controlled_by, controller_principal_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING *
        """,
        (
            campaign_id,
            data["entity_type"],
            data["name"],
            data.get("tags", []),
            json.dumps(data.get("public_sheet", {})),
            json.dumps(data.get("secret_sheet", {})),
            data.get("hp_current"),
            data.get("hp_max"),
            data.get("ac"),
            data.get("speed"),
            data.get("controlled_by", "HUMAN"),
            data.get("controller_principal_id"),
        ),
    )


def _queue_rag_processing(doc_id: str):
    RAG_EXECUTOR.submit(_process_rag_document, doc_id)


def _process_rag_document(doc_id: str):
    from shared.db.connection import execute_one, execute_query
    from services.llm.adapter import LLMAdapter

    doc = execute_one("SELECT * FROM state.rag_documents WHERE id=%s", (doc_id,))
    if not doc:
        return

    campaign_id = str(doc["campaign_id"])
    try:
        execute_one(
            "UPDATE state.rag_documents SET status='PROCESSING', error_text=NULL, updated_at=now() WHERE id=%s RETURNING id",
            (doc_id,),
        )
        chunks = _extract_text_chunks(doc["storage_path"])
        llm = LLMAdapter(campaign_id=uuid.UUID(campaign_id), role="dm")
        embedding_result = llm.embed_texts([c["text"] for c in chunks]) if chunks else {"vectors": [], "dimensions": 0}
        vectors = embedding_result["vectors"]
        dims = embedding_result["dimensions"]

        execute_query("DELETE FROM state.rag_chunks WHERE doc_id=%s", (doc_id,), fetch=False)
        if dims > 0:
            try:
                _delete_qdrant_doc_points(campaign_id, doc_id)
            except Exception:
                logging.exception("Failed deleting prior qdrant points for doc_id=%s", doc_id)

        points = []
        for i, chunk in enumerate(chunks):
            qid = f"{doc_id}:{chunk['chunk_id']}"
            execute_one(
                """
                INSERT INTO state.rag_chunks (doc_id, campaign_id, chunk_id, page, text, qdrant_point_id, metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    doc_id,
                    campaign_id,
                    chunk["chunk_id"],
                    chunk["page"],
                    chunk["text"],
                    qid,
                    json.dumps({"source_filename": doc["filename"], "vector_dim": len(vectors[i]) if vectors else 0}),
                ),
            )
            if vectors:
                points.append(
                    {
                        "id": qid,
                        "vector": vectors[i],
                        "payload": {
                            "campaign_id": campaign_id,
                            "doc_id": doc_id,
                            "chunk_id": chunk["chunk_id"],
                            "page": chunk["page"],
                            "source_filename": doc["filename"],
                            "text": chunk["text"],
                        },
                    }
                )

        if points and dims > 0:
            _upsert_qdrant_points(campaign_id, points, dims)

        execute_one(
            "UPDATE state.rag_documents SET status='READY', error_text=NULL, updated_at=now() WHERE id=%s RETURNING id",
            (doc_id,),
        )
    except Exception as exc:
        logging.exception("RAG processing failed for doc_id=%s", doc_id)
        execute_one(
            "UPDATE state.rag_documents SET status='FAILED', error_text=%s, updated_at=now() WHERE id=%s RETURNING id",
            (str(exc), doc_id),
        )


@app.route("/api/campaigns")
def api_campaigns():
    from shared.db.connection import execute_query

    rows = execute_query("SELECT * FROM state.campaigns ORDER BY created_at DESC")
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/campaigns/<campaign_id>")
def api_campaign(campaign_id):
    from shared.db.connection import execute_one

    row = execute_one("SELECT * FROM state.campaigns WHERE id = %s", (campaign_id,))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_serialize(row))


@app.route("/api/campaigns/<campaign_id>/entities")
def api_entities(campaign_id):
    from shared.db.connection import execute_query

    rows = execute_query(
        """
        SELECT e.*, p.display_name as controller_name
        FROM state.entities e
        LEFT JOIN state.principals p ON e.controller_principal_id = p.id
        WHERE e.campaign_id = %s ORDER BY e.entity_type, e.name
    """,
        (campaign_id,),
    )
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/campaigns/<campaign_id>/encounters")
def api_encounters(campaign_id):
    from shared.db.connection import execute_query

    rows = execute_query(
        """
        SELECT * FROM state.encounters WHERE campaign_id = %s ORDER BY created_at DESC
    """,
        (campaign_id,),
    )
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/campaigns/<campaign_id>/members")
def api_campaign_members(campaign_id):
    """List all principals who are members of this campaign."""
    from shared.db.connection import execute_query

    rows = execute_query(
        """
        SELECT cm.principal_id, cm.role, p.display_name, p.principal_type
        FROM state.campaign_members cm
        JOIN state.principals p ON cm.principal_id = p.id
        WHERE cm.campaign_id = %s AND p.is_active = true
        ORDER BY cm.role, p.display_name
        """,
        (campaign_id,),
    )
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/campaigns/<campaign_id>/session")
def api_campaign_session(campaign_id):
    from shared.db.connection import execute_one
    from shared.auth.principal import load_principal

    principal_id = request.args.get("principal_id")
    if not principal_id:
        return jsonify({"error": "principal_id is required"}), 400

    try:
        campaign_uuid = uuid.UUID(campaign_id)
        principal_uuid = uuid.UUID(principal_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid campaign_id or principal_id format"}), 400

    principal = load_principal(principal_uuid, campaign_uuid)
    if not principal or not principal.role:
        return jsonify({"error": "Principal is not a campaign member"}), 403
    if not principal.is_gm():
        return jsonify({"error": "Only GM can load session"}), 403

    session_record = execute_one(
        """
        SELECT id, status
        FROM state.sessions
        WHERE campaign_id = %s AND status = 'ACTIVE'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (str(campaign_uuid),),
    )
    if not session_record:
        return jsonify({"error": "No session found for campaign"}), 404

    encounter = execute_one(
        """
        SELECT id AS encounter_id, status, round_number
        FROM state.encounters
        WHERE session_id = %s AND status = 'ACTIVE'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (str(session_record["id"]),),
    )

    return jsonify(
        {
            "campaign_id": str(campaign_uuid),
            "session_id": str(session_record["id"]),
            "encounter_id": str(encounter["encounter_id"]) if encounter else None,
            "encounter_status": encounter["status"] if encounter else None,
            "round_number": encounter["round_number"] if encounter else 0,
        }
    )


@app.route("/api/sessions/<session_id>/join", methods=["POST"])
def api_join_session(session_id):
    from shared.db.connection import execute_one
    from shared.auth.principal import load_principal

    data = request.get_json(silent=True) or {}
    principal_id = data.get("principal_id")
    if not principal_id:
        return jsonify({"error": "principal_id is required"}), 400

    try:
        session_uuid = uuid.UUID(session_id)
        principal_uuid = uuid.UUID(principal_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid id format"}), 400

    session_record = execute_one(
        """
        SELECT campaign_id
        FROM state.sessions
        WHERE id = %s AND status = 'ACTIVE'
        LIMIT 1
        """,
        (str(session_uuid),),
    )
    if not session_record:
        return jsonify({"error": "Session not found"}), 404

    campaign_uuid = uuid.UUID(str(session_record["campaign_id"]))
    principal = load_principal(principal_uuid, campaign_uuid)
    if not principal or not principal.role:
        return jsonify({"error": "Principal is not a campaign member"}), 403

    return jsonify(
        {
            "joined": True,
            "session_id": str(session_uuid),
            "campaign_id": str(campaign_uuid),
            "principal_id": str(principal_uuid),
            "role": principal.role,
        }
    )


@app.route("/api/campaigns/<campaign_id>/mode", methods=["GET", "POST"])
def api_campaign_mode(campaign_id):
    from services.orchestrator.state_machine import StateMachine
    from shared.schemas.enums import GameMode

    sm = StateMachine()

    if request.method == "GET":
        mode = sm.get_campaign_mode(uuid.UUID(campaign_id))
        return jsonify({"mode": mode.value})

    data = request.get_json()
    new_mode = GameMode(data["mode"])
    result = sm.set_campaign_mode(uuid.UUID(campaign_id), new_mode)
    return jsonify(result)


@app.route("/api/campaigns/<campaign_id>/maps")
def api_maps(campaign_id):
    from shared.db.connection import execute_query

    rows = execute_query(
        "SELECT * FROM state.maps WHERE campaign_id = %s", (campaign_id,)
    )
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/maps/<map_id>")
def api_map_detail(map_id):
    from services.domain.maps.system import MapSystem

    ms = MapSystem()
    data = ms.get_map_data(uuid.UUID(map_id))
    return jsonify(_serialize(data))


@app.route("/api/maps/<map_id>/children")
def api_map_children(map_id):
    """Direct child maps (drilldown) — e.g. all rooms inside an area."""
    from shared.db.connection import execute_query

    rows = execute_query(
        "SELECT id, name, kind, width, height, parent_map_id "
        "FROM state.maps WHERE parent_map_id = %s ORDER BY name",
        (map_id,),
    )
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/maps/<map_id>/decorations")
def api_map_decorations(map_id):
    """Visual flavor objects on a map (trees, barrels, torches, etc.).
    Decorations are non-interactive — they just make a map look like a place."""
    from shared.db.connection import execute_query
    rows = execute_query(
        "SELECT * FROM state.map_decorations WHERE map_id = %s ORDER BY y, x",
        (map_id,),
    )
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/maps/<map_id>/pois")
def api_map_pois(map_id):
    """All POIs on a map. GM/AI-DM view; clients should use discovered_pois
    to get the proximity-filtered, hidden-aware list for a player."""
    from shared.db.connection import execute_query

    rows = execute_query(
        "SELECT * FROM state.map_pois WHERE map_id = %s ORDER BY x, y",
        (map_id,),
    )
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/maps/<map_id>/pois", methods=["POST"])
def api_map_poi_create(map_id):
    """Create a POI on a map. Body: { x, y, kind, name, description?, image_url?, target_map_id?, is_hidden?, metadata? }"""
    from shared.db.connection import execute_one

    data = request.get_json(silent=True) or {}
    required = ("x", "y", "kind", "name")
    missing = [k for k in required if data.get(k) is None]
    if missing:
        return jsonify({"error": f"missing fields: {missing}"}), 400
    valid_kinds = {"NPC", "BUILDING", "SIGN", "HAZARD", "TREASURE", "PORTAL", "GENERIC"}
    if data["kind"] not in valid_kinds:
        return jsonify({"error": f"kind must be one of {sorted(valid_kinds)}"}), 400
    row = execute_one(
        """
        INSERT INTO state.map_pois
          (map_id, x, y, kind, name, description, image_url, target_map_id, is_hidden, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        RETURNING *
        """,
        (
            map_id,
            int(data["x"]),
            int(data["y"]),
            data["kind"],
            data["name"],
            data.get("description"),
            data.get("image_url"),
            data.get("target_map_id"),
            bool(data.get("is_hidden", False)),
            json.dumps(data.get("metadata") or {}),
        ),
    )
    return jsonify(_serialize(row)), 201


@app.route("/api/pois/<poi_id>", methods=["PUT"])
def api_poi_update(poi_id):
    """Patch a POI. Accepts any subset of name/description/x/y/kind/target_map_id/is_hidden/metadata."""
    from shared.db.connection import execute_one

    data = request.get_json(silent=True) or {}
    allowed = ("name", "description", "x", "y", "kind", "target_map_id", "is_hidden", "metadata")
    sets, params = [], []
    for k in allowed:
        if k in data:
            if k == "metadata":
                sets.append("metadata = %s::jsonb")
                params.append(json.dumps(data[k] or {}))
            else:
                sets.append(f"{k} = %s")
                params.append(data[k])
    if not sets:
        return jsonify({"error": "no updatable fields provided"}), 400
    params.append(poi_id)
    row = execute_one(
        f"UPDATE state.map_pois SET {', '.join(sets)}, updated_at = now() WHERE id = %s RETURNING *",
        tuple(params),
    )
    if not row:
        return jsonify({"error": "POI not found"}), 404
    return jsonify(_serialize(row))


@app.route("/api/pois/<poi_id>", methods=["DELETE"])
def api_poi_delete(poi_id):
    from shared.db.connection import execute_one

    row = execute_one("DELETE FROM state.map_pois WHERE id = %s RETURNING id", (poi_id,))
    if not row:
        return jsonify({"error": "POI not found"}), 404
    return jsonify({"deleted": str(row["id"])})


@app.route("/api/pois/<poi_id>/image", methods=["POST"])
def api_poi_image_upload(poi_id):
    """Upload or set the image for a POI. Mirrors entity-portrait flow:
    - file upload as data URL (capped at 2MB), OR
    - JSON body with image_url to use a remote URL (e.g. one returned by an
      OpenRouter image-gen call later in Phase 6e)."""
    from shared.db.connection import execute_one
    import base64

    poi = execute_one("SELECT id FROM state.map_pois WHERE id = %s", (poi_id,))
    if not poi:
        return jsonify({"error": "POI not found"}), 404

    if "file" in request.files:
        f = request.files["file"]
        if f.filename == "":
            return jsonify({"error": "No file selected"}), 400
        allowed = {"png", "jpg", "jpeg", "gif", "webp"}
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in allowed:
            return jsonify({"error": f"Invalid file type. Allowed: {allowed}"}), 400
        content = f.read()
        if len(content) > 2 * 1024 * 1024:
            return jsonify({"error": "File too large. Max 2MB"}), 400
        mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
        data_url = f"data:{mime};base64,{base64.b64encode(content).decode()}"
        row = execute_one(
            "UPDATE state.map_pois SET image_url = %s, updated_at = now() WHERE id = %s RETURNING *",
            (data_url, poi_id),
        )
        return jsonify(_serialize(row))

    body = request.get_json(silent=True) or {}
    if body.get("image_url"):
        row = execute_one(
            "UPDATE state.map_pois SET image_url = %s, updated_at = now() WHERE id = %s RETURNING *",
            (body["image_url"], poi_id),
        )
        return jsonify(_serialize(row))
    return jsonify({"error": "No image provided"}), 400


@app.route("/api/_debug/save_canvas", methods=["POST"])
def api_debug_save_canvas():
    """One-shot debug helper to write a base64 data-URL to disk so we can
    inspect what the renderer drew. Saves under burn-bag/canvas-snaps/."""
    import base64
    data = request.get_json(silent=True) or {}
    url = data.get("data_url") or ""
    name = data.get("name") or f"snap-{uuid.uuid4().hex[:8]}.png"
    if not url.startswith("data:image/png;base64,"):
        return jsonify({"error": "data_url must be a base64 png"}), 400
    payload = base64.b64decode(url.split(",", 1)[1])
    out_dir = Path("burn-bag/canvas-snaps")
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = secure_filename(name) or f"snap-{uuid.uuid4().hex[:8]}.png"
    out_path = (out_dir / safe).resolve()
    out_path.write_bytes(payload)
    return jsonify({"saved": str(out_path), "bytes": len(payload)})


@app.route("/api/entities/<entity_id>/transition_map", methods=["POST"])
def api_entity_transition_map(entity_id):
    """Move an entity to a different map (and optionally a starting position).

    Used when a PC walks through a portal POI, moves between rooms, etc.
    Body: {"map_id": "...", "x": 5, "y": 5}
    """
    from services.domain.maps.decoherence import transition_entity_map

    data = request.get_json(silent=True) or {}
    map_id = data.get("map_id")
    if not map_id:
        return jsonify({"error": "map_id required"}), 400
    try:
        row = transition_entity_map(
            uuid.UUID(entity_id),
            uuid.UUID(map_id),
            x=data.get("x"),
            y=data.get("y"),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(_serialize(row))


@app.route("/api/events/audience", methods=["POST"])
def api_event_audience():
    """Compute which principals should witness an event at (map_id, x, y).

    Pure read endpoint, intended for the orchestrator and AI-DM heuristics
    to consult before deciding what to push. The WebSocket broadcaster will
    eventually use this internally; for now it's exposed for inspection.
    """
    from services.domain.maps.decoherence import audience_for_event

    data = request.get_json(silent=True) or {}
    cid = data.get("campaign_id")
    if not cid:
        return jsonify({"error": "campaign_id required"}), 400
    audience = audience_for_event(
        campaign_id=uuid.UUID(cid),
        map_id=uuid.UUID(data["map_id"]) if data.get("map_id") else None,
        x=data.get("x"),
        y=data.get("y"),
    )
    return jsonify({"audience": audience})


@app.route("/api/decorations/<deco_id>/generate_image", methods=["POST"])
def api_decoration_generate_image(deco_id):
    """Generate art for a decoration via the campaign's configured image
    provider (OpenRouter / OpenAI / etc). Same flow as POI generation."""
    from shared.db.connection import execute_one
    from services.domain.maps.image_gen import generate_poi_image, ImageGenError

    deco = execute_one(
        "SELECT d.*, m.campaign_id FROM state.map_decorations d "
        "JOIN state.maps m ON d.map_id = m.id WHERE d.id = %s",
        (deco_id,),
    )
    if not deco:
        return jsonify({"error": "decoration not found"}), 404
    body = request.get_json(silent=True) or {}
    try:
        url = generate_poi_image(
            campaign_id=deco["campaign_id"],
            name=deco["kind"].title(),
            kind=deco["kind"],
            description=None,
            style_hint=body.get("style_hint")
                or "PS1-era pixel art object on transparent background, top-down, crisp pixels, no antialiasing",
        )
    except ImageGenError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": f"Image generation crashed: {e}"}), 500
    row = execute_one(
        "UPDATE state.map_decorations SET image_url = %s WHERE id = %s RETURNING *",
        (url, deco_id),
    )
    return jsonify(_serialize(row))


@app.route("/api/campaigns/<campaign_id>/test_image_gen", methods=["POST"])
def api_test_image_gen(campaign_id):
    """One-shot smoke test for the campaign's configured image provider.
    Used by the AI Settings 'Test Image Gen' button. Doesn't write anything;
    returns the raw provider response (URL or data:URL).

    Body (optional): {"prompt": "..."} to override the default test prompt.
    """
    from services.domain.maps.image_gen import (
        generate_poi_image, ImageGenError, _campaign_image_config
    )

    body = request.get_json(silent=True) or {}
    cfg = _campaign_image_config(uuid.UUID(campaign_id))
    if not cfg["api_key"]:
        return jsonify({
            "ok": False,
            "error": f"No API key configured for image provider '{cfg['provider']}'. Save one in AI Settings → Image Generation."
        }), 400
    try:
        url = generate_poi_image(
            campaign_id=uuid.UUID(campaign_id),
            name=body.get("prompt") or "Smoke test object",
            kind="GENERIC",
            description="A small wooden chest",
            style_hint=body.get("style_hint") or "PS1-era pixel art, crisp pixels",
        )
    except ImageGenError as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": f"crashed: {e}"}), 500
    return jsonify({
        "ok": True,
        "provider": cfg["provider"],
        "model": cfg["model"],
        "image_url_preview": url[:80] + "…" if len(url) > 80 else url,
        "image_url": url,  # full URL/data-URL so the UI can display it
    })


@app.route("/api/pois/<poi_id>/generate_image", methods=["POST"])
def api_poi_generate_image(poi_id):
    """Generate an image for a POI via the campaign's configured image provider.
    Stores the result in the POI's image_url and returns the row.
    Body (optional): {"style_hint": "..."}
    """
    from shared.db.connection import execute_one
    from services.domain.maps.image_gen import generate_poi_image, ImageGenError

    poi = execute_one(
        "SELECT p.*, m.campaign_id FROM state.map_pois p "
        "JOIN state.maps m ON p.map_id = m.id WHERE p.id = %s",
        (poi_id,),
    )
    if not poi:
        return jsonify({"error": "POI not found"}), 404

    body = request.get_json(silent=True) or {}
    try:
        url = generate_poi_image(
            campaign_id=poi["campaign_id"],
            name=poi["name"],
            kind=poi["kind"],
            description=poi.get("description"),
            style_hint=body.get("style_hint")
                or "PS1-era pixel art, top-down, isometric, crisp pixels, no antialiasing",
        )
    except ImageGenError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": f"Image generation crashed: {e}"}), 500

    row = execute_one(
        "UPDATE state.map_pois SET image_url = %s, updated_at = now() WHERE id = %s RETURNING *",
        (url, poi_id),
    )
    return jsonify(_serialize(row))


@app.route("/api/pois/<poi_id>/image", methods=["DELETE"])
def api_poi_image_delete(poi_id):
    from shared.db.connection import execute_one

    row = execute_one(
        "UPDATE state.map_pois SET image_url = NULL, updated_at = now() WHERE id = %s RETURNING *",
        (poi_id,),
    )
    if not row:
        return jsonify({"error": "POI not found"}), 404
    return jsonify(_serialize(row))


@app.route("/api/entities/<entity_id>/discovered_pois")
def api_discovered_pois(entity_id):
    """POIs the entity can currently see, given their position and class.

    Optional query param ``map_id``: which map to read from. If omitted, the
    entity's `current_map_id` would be used — but that column doesn't exist
    yet (Phase 4 keeps a single map per campaign), so map_id is required.
    """
    from shared.db.connection import execute_one, execute_query
    from services.domain.maps.perception import discovered_pois

    map_id = request.args.get("map_id")
    if not map_id:
        return jsonify({"error": "map_id query param required"}), 400

    entity = execute_one(
        "SELECT * FROM state.entities WHERE id = %s",
        (entity_id,),
    )
    if not entity:
        return jsonify({"error": "entity not found"}), 404

    pois = execute_query(
        "SELECT * FROM state.map_pois WHERE map_id = %s",
        (map_id,),
    )
    visible = [
        p for p in discovered_pois(dict(entity), [dict(p) for p in pois])
        if not p.get("is_hidden")
    ]
    return jsonify([_serialize(p) for p in visible])


@app.route("/api/propose", methods=["POST"])
def api_propose():
    data = request.get_json()
    try:
        from shared.schemas.contracts import InterventionProposal
        from shared.auth.principal import load_principal
        from services.orchestrator.pipeline import OrchestratorPipeline

        proposal = InterventionProposal(
            action_type=data["action_type"],
            params=data.get("params", {}),
            proposer_principal_id=uuid.UUID(data["principal_id"]),
            campaign_id=uuid.UUID(data["campaign_id"]),
            session_id=uuid.UUID(
                data.get("session_id", "66666666-6666-6666-6666-666666666661")
            ),
            encounter_id=uuid.UUID(data["encounter_id"])
            if data.get("encounter_id")
            else None,
            idempotency_key=data.get("idempotency_key"),
            domain_tags=data.get("domain_tags", []),
        )

        principal = load_principal(proposal.proposer_principal_id, proposal.campaign_id)
        if not principal:
            return jsonify({"error": "Principal not found"}), 404

        pipeline = OrchestratorPipeline()
        session_id = proposal.session_id
        result = pipeline.process_proposal(proposal, principal, session_id)

        socketio.emit("game_event", result, room=str(proposal.campaign_id))

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 400


@app.route("/api/dice/roll", methods=["POST"])
def api_roll_dice():
    data = request.get_json()
    from services.mechanics.dice import roll_dice

    try:
        result = roll_dice(data["notation"], data.get("modifier", 0))
        return jsonify(result.model_dump())
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/encounters/<encounter_id>/advance", methods=["POST"])
def api_advance_turn(encounter_id):
    from services.orchestrator.state_machine import StateMachine

    sm = StateMachine()
    result = sm.advance_turn(uuid.UUID(encounter_id))
    socketio.emit("turn_advanced", result, room="encounter_" + encounter_id)
    return jsonify(result)


@app.route("/api/encounters/<encounter_id>/slots")
def api_encounter_slots(encounter_id):
    from services.orchestrator.state_machine import StateMachine

    sm = StateMachine()
    slots = sm.get_encounter_slots(uuid.UUID(encounter_id))
    return jsonify([_serialize(s) for s in slots])


@app.route("/api/encounters/<encounter_id>/auto_advance", methods=["POST"])
def api_auto_advance(encounter_id):
    """Process AI-controlled entity turns automatically."""
    from services.orchestrator.npc_autonomy import NPCAutonomy
    from services.orchestrator.state_machine import StateMachine
    from shared.db.connection import execute_one

    sm = StateMachine()
    autonomy = NPCAutonomy()

    encounter = execute_one(
        "SELECT * FROM state.encounters WHERE id = %s",
        (encounter_id,)
    )
    if not encounter:
        return jsonify({"error": "Encounter not found"}), 404

    active_slot = sm.get_active_slot(uuid.UUID(encounter_id))
    if not active_slot:
        return jsonify({"error": "No active slot"}), 400

    # Check if current entity is AI-controlled
    entity = execute_one(
        "SELECT * FROM state.entities WHERE id = %s",
        (str(active_slot.get("entity_id")),)
    )

    if not entity or entity.get("controlled_by") not in ("AI", "AI_NPC"):
        return jsonify({
            "processed": False,
            "reason": "Human-controlled entity",
            "entity_name": entity.get("name") if entity else "Unknown",
        })

    # Process AI turn
    campaign_id = uuid.UUID(str(encounter["campaign_id"]))
    session_id = uuid.UUID(str(encounter.get("session_id", "66666666-6666-6666-6666-666666666661")))

    results = autonomy.process_npc_turn(
        campaign_id=campaign_id,
        session_id=session_id,
        encounter_id=uuid.UUID(encounter_id),
        entity_id=uuid.UUID(str(active_slot.get("entity_id"))),
    )

    # Broadcast results
    for result in results:
        socketio.emit("game_event", result, room=str(campaign_id))

    return jsonify({
        "processed": True,
        "entity_name": entity.get("name"),
        "actions": len(results),
        "results": results,
    })


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json()
    try:
        from services.conversations.manager import ConversationManager

        campaign_uuid = uuid.UUID(data["campaign_id"])
        cm = ConversationManager(campaign_id=campaign_uuid)
        events = cm.handle_proximity_chat(
            campaign_id=uuid.UUID(data["campaign_id"]),
            session_id=uuid.UUID(
                data.get("session_id", "66666666-6666-6666-6666-666666666661")
            ),
            speaker_entity_id=uuid.UUID(data["speaker_entity_id"]),
            speaker_principal_id=uuid.UUID(data["speaker_principal_id"]),
            message=data["message"],
            target_entity_id=uuid.UUID(data["target_entity_id"])
            if data.get("target_entity_id")
            else None,
        )

        from services.ledger.writer import LedgerWriter

        ledger = LedgerWriter()
        results = []
        for event in events:
            r = ledger.append_event(event)
            results.append(r)
            socketio.emit(
                "game_event",
                _serialize(event.model_dump()),
                room=str(data["campaign_id"]),
            )

        return jsonify({"events_created": len(results), "results": results})
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 400


@app.route("/api/narrate", methods=["POST"])
def api_narrate():
    data = request.get_json()
    try:
        from services.llm.adapter import DMNarrationAgent
        import uuid as uuid_mod

        campaign_id = data.get("campaign_id")
        campaign_uuid = uuid_mod.UUID(campaign_id) if campaign_id else None
        dm = DMNarrationAgent(campaign_id=campaign_uuid)
        narration = dm.narrate_event(
            tool_result=data.get("event_data", {}),
            context=data.get("context", ""),
        )
        return jsonify({"narration": narration})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/content/check", methods=["POST"])
def api_content_check():
    data = request.get_json()
    from services.domain.content_rating.gate import ContentRatingGate
    from shared.schemas.enums import ContentRating

    rating = ContentRating(data.get("rating", "SAFE"))
    gate = ContentRatingGate(rating)
    result = gate.check_content(data.get("text", ""))
    return jsonify(result)


@app.route("/api/export/<session_id>")
def api_export(session_id):
    principal_id = request.args.get("principal_id")
    campaign_id = request.args.get("campaign_id")
    if not principal_id or not campaign_id:
        return jsonify({"error": "principal_id and campaign_id required"}), 400

    from services.export.exporter import SessionExporter

    exporter = SessionExporter()
    try:
        md = exporter.export_to_markdown(
            uuid.UUID(session_id), uuid.UUID(principal_id), uuid.UUID(campaign_id)
        )
        return Response(
            md,
            mimetype="text/markdown",
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}.md"
            },
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _ensure_default_human_principal():
    """Return the id of a HUMAN principal usable as the default GM, creating
    one on first call. Without a HUMAN member tied to a campaign, the game
    UI can't elect a principal_id and click/WASD/attack all silently no-op
    (canControl returns false for every entity)."""
    from shared.db.connection import execute_one

    existing = execute_one(
        "SELECT id FROM state.principals WHERE auth_subject='local:player' AND is_active = true LIMIT 1"
    )
    if existing:
        return existing["id"]
    row = execute_one(
        """
        INSERT INTO state.principals (principal_type, display_name, auth_subject, is_active)
        VALUES ('HUMAN', 'LocalPlayer', 'local:player', true)
        RETURNING id
        """,
    )
    return row["id"]


def _attach_default_gm(campaign_id):
    """Add the default HUMAN principal as GM of a campaign (idempotent)."""
    from shared.db.connection import execute_one

    pid = _ensure_default_human_principal()
    execute_one(
        """
        INSERT INTO state.campaign_members (campaign_id, principal_id, role)
        VALUES (%s, %s, 'GM')
        ON CONFLICT (campaign_id, principal_id) DO NOTHING
        RETURNING principal_id
        """,
        (campaign_id, str(pid)),
    )


@app.route("/api/campaigns", methods=["POST"])
def api_campaigns_create():
    from shared.db.connection import execute_one

    data = request.get_json(silent=True) or {}
    err = _validate_campaign_payload(data)
    if err:
        return jsonify({"error": err}), 400

    row = execute_one(
        """
        INSERT INTO state.campaigns (slug, name, status, mode)
        VALUES (%s, %s, %s, %s)
        RETURNING *
        """,
        (data["slug"], data["name"], data["status"], data["mode"]),
    )
    # Tie the default LocalPlayer human to the new campaign as GM. Without this,
    # the game UI has no principal to act as, so click/WASD/attack all no-op.
    try:
        _attach_default_gm(str(row["id"]))
    except Exception:
        app.logger.exception("failed to attach default GM to campaign %s", row["id"])
    return jsonify(_serialize(row)), 201


@app.route("/api/campaigns/<campaign_id>", methods=["PUT"])
def api_campaign_update(campaign_id):
    from shared.db.connection import execute_one

    data = request.get_json(silent=True) or {}
    err = _validate_campaign_payload(data, partial=True)
    if err:
        return jsonify({"error": err}), 400

    fields, params = [], []
    for key in ("name", "slug", "status", "mode"):
        if key in data:
            fields.append(f"{key} = %s")
            params.append(data[key])
    if not fields:
        return jsonify({"error": "no updatable fields provided"}), 400
    params.append(campaign_id)

    row = execute_one(
        f"UPDATE state.campaigns SET {', '.join(fields)}, updated_at=now() WHERE id=%s RETURNING *",
        tuple(params),
    )
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_serialize(row))


@app.route("/api/campaigns/<campaign_id>", methods=["DELETE"])
def api_campaign_tombstone(campaign_id):
    from shared.db.connection import execute_one

    row = execute_one(
        "UPDATE state.campaigns SET status='TOMBSTONED', updated_at=now() WHERE id=%s RETURNING *",
        (campaign_id,),
    )
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_serialize(row))


def _cascade_delete_campaign(campaign_id: str) -> bool:
    """Hard-delete a campaign and every row that depends on it.

    Runs as a single transaction. Children-before-parents order, so FKs
    declared NO ACTION don't block. Tables already declared ON DELETE
    CASCADE in the schema are listed redundantly here — the explicit DELETE
    is a no-op once the parent's gone, but we list them so the order is
    obvious from reading the code.

    Returns True if a campaign row was deleted.
    """
    from shared.db.connection import transaction

    cid = (campaign_id,)
    DELETES = [
        # Ledger (no FK to campaigns, just a column)
        "DELETE FROM ledger.session_ledger WHERE campaign_id = %s",
        # Entity- and encounter-level grandchildren
        "DELETE FROM state.encounter_slots WHERE encounter_id IN (SELECT id FROM state.encounters WHERE campaign_id = %s)",
        "DELETE FROM state.conditions WHERE entity_id IN (SELECT id FROM state.entities WHERE campaign_id = %s) OR encounter_id IN (SELECT id FROM state.encounters WHERE campaign_id = %s)",
        "DELETE FROM state.intents WHERE campaign_id = %s",
        "DELETE FROM state.interventions WHERE campaign_id = %s",
        "DELETE FROM state.divine_standings WHERE campaign_id = %s",
        "DELETE FROM state.faction_memberships WHERE entity_id IN (SELECT id FROM state.entities WHERE campaign_id = %s) OR faction_id IN (SELECT id FROM state.factions WHERE campaign_id = %s)",
        "DELETE FROM state.faction_wars WHERE campaign_id = %s",
        "DELETE FROM state.bounties WHERE campaign_id = %s",
        "DELETE FROM state.shop_inventory WHERE shop_id IN (SELECT id FROM state.shops WHERE campaign_id = %s) OR item_entity_id IN (SELECT id FROM state.entities WHERE campaign_id = %s)",
        "DELETE FROM state.location_metrics WHERE location_entity_id IN (SELECT id FROM state.entities WHERE campaign_id = %s)",
        "DELETE FROM state.property_ownership WHERE property_entity_id IN (SELECT id FROM state.entities WHERE campaign_id = %s) OR owner_entity_id IN (SELECT id FROM state.entities WHERE campaign_id = %s)",
        "DELETE FROM state.reaction_triggers WHERE campaign_id = %s",
        "DELETE FROM state.entity_death_history WHERE campaign_id = %s",  # CASCADEd, redundant
        "DELETE FROM state.session_characters WHERE session_id IN (SELECT id FROM state.sessions WHERE campaign_id = %s)",
        "DELETE FROM state.price_modifiers WHERE campaign_id = %s",
        # Mid-tier (children of campaign)
        "DELETE FROM state.encounters WHERE campaign_id = %s",
        "DELETE FROM state.shops WHERE campaign_id = %s",
        "DELETE FROM state.factions WHERE campaign_id = %s",
        "DELETE FROM state.map_nodes WHERE map_id IN (SELECT id FROM state.maps WHERE campaign_id = %s)",
        "DELETE FROM state.map_pois WHERE map_id IN (SELECT id FROM state.maps WHERE campaign_id = %s)",  # CASCADEd, redundant
        # Entities reference current_map_id (SET NULL on map delete) so order
        # of maps vs entities doesn't matter, but doing entities first keeps
        # entity-children deletes self-contained.
        "DELETE FROM state.entities WHERE campaign_id = %s",
        "DELETE FROM state.maps WHERE campaign_id = %s",
        # Sessions and their direct dependents
        "DELETE FROM state.story_state_history WHERE session_id IN (SELECT id FROM state.sessions WHERE campaign_id = %s)",
        "DELETE FROM state.story_state WHERE campaign_id = %s",  # CASCADEd, redundant
        "DELETE FROM state.session_archives WHERE campaign_id = %s",  # CASCADEd, redundant
        "DELETE FROM state.sessions WHERE campaign_id = %s",
        # Per-campaign metadata
        "DELETE FROM state.rag_chunks WHERE campaign_id = %s",  # CASCADEd, redundant
        "DELETE FROM state.rag_documents WHERE campaign_id = %s",  # CASCADEd, redundant
        "DELETE FROM state.campaign_settings WHERE campaign_id = %s",  # CASCADEd, redundant
        "DELETE FROM state.campaign_members WHERE campaign_id = %s",
        # Finally, the campaign row itself.
        "DELETE FROM state.campaigns WHERE id = %s RETURNING id",
    ]

    deleted = False
    with transaction() as conn:
        with conn.cursor() as cur:
            # The schema has a trigger `trg_archive_session` that auto-archives
            # a session when it's DELETEd. It's currently broken (references a
            # `sessions.name` column that no longer exists) AND semantically wrong
            # for purge — purging means destroy, not archive. Disable for the txn.
            cur.execute("ALTER TABLE state.sessions DISABLE TRIGGER trg_archive_session")
            try:
                for sql in DELETES:
                    placeholders = sql.count("%s")
                    cur.execute(sql, cid * placeholders)
                    if "FROM state.campaigns WHERE id" in sql and cur.rowcount > 0:
                        deleted = True
            finally:
                cur.execute("ALTER TABLE state.sessions ENABLE TRIGGER trg_archive_session")
    return deleted


@app.route("/api/campaigns/<campaign_id>/purge", methods=["POST"])
def api_campaign_purge(campaign_id):
    """Permanently delete a campaign and every row that ties to it.

    Irreversible. Use Archive (DELETE /api/campaigns/<id>) for soft delete.
    """
    try:
        ok = _cascade_delete_campaign(campaign_id)
    except Exception as e:
        app.logger.exception("purge failed for %s", campaign_id)
        return jsonify({"error": f"purge failed: {e}"}), 500
    if not ok:
        return jsonify({"error": "campaign not found"}), 404
    return jsonify({"deleted": campaign_id, "warning": "PURGE is irreversible"})


@app.route("/api/campaigns/<campaign_id>/resume", methods=["POST"])
def api_campaign_resume(campaign_id):
    from shared.db.connection import execute_one

    active = execute_one(
        "SELECT * FROM state.sessions WHERE campaign_id=%s AND status='ACTIVE' ORDER BY created_at DESC LIMIT 1",
        (campaign_id,),
    )
    if active:
        return jsonify({"session": _serialize(active), "created": False})
    row = execute_one(
        "INSERT INTO state.sessions (campaign_id, status) VALUES (%s, 'ACTIVE') RETURNING *",
        (campaign_id,),
    )
    return jsonify({"session": _serialize(row), "created": True}), 201


@app.route("/api/campaigns/<campaign_id>/sessions")
def api_campaign_sessions(campaign_id):
    from shared.db.connection import execute_query

    rows = execute_query(
        "SELECT * FROM state.sessions WHERE campaign_id=%s ORDER BY created_at DESC",
        (campaign_id,),
    )
    return jsonify([_serialize(r) for r in rows])


def _ensure_starter_map(campaign_id: str) -> None:
    """Generate the World/Area/Room hierarchy for a campaign that has none.

    Deterministic: seed derives from the campaign_id so re-runs reproduce the
    same layout. Idempotent: skips generation when any map already exists.
    """
    from shared.db.connection import execute_one
    from services.domain.maps.system import ProceduralMapGenerator

    existing = execute_one(
        "SELECT id FROM state.maps WHERE campaign_id = %s LIMIT 1",
        (campaign_id,),
    )
    if existing:
        return

    seed = int(hashlib.sha1(campaign_id.encode("utf-8")).hexdigest()[:8], 16)
    ProceduralMapGenerator().generate_starter_world(
        campaign_id=uuid.UUID(campaign_id),
        seed=seed,
    )


@app.route("/api/campaigns/<campaign_id>/sessions", methods=["POST"])
def api_campaign_sessions_create(campaign_id):
    from shared.db.connection import transaction

    with transaction() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "UPDATE state.sessions SET status='ENDED', ended_at=now(), updated_at=now() WHERE campaign_id=%s AND status='ACTIVE'",
                (campaign_id,),
            )
            cur.execute(
                "INSERT INTO state.sessions (campaign_id, status) VALUES (%s, 'ACTIVE') RETURNING *",
                (campaign_id,),
            )
            row = cur.fetchone()

    # Generate a starter map for first-time campaigns. Done after the session
    # transaction commits so a slow generator can't roll back the session.
    try:
        _ensure_starter_map(campaign_id)
    except Exception:
        # Map gen failures should not block session creation. The user can
        # still play; the GM can retry by adding a map manually later.
        app.logger.exception("starter map generation failed for %s", campaign_id)

    return jsonify(_serialize(row)), 201


def _set_session_status(session_id, status):
    from shared.db.connection import execute_one

    ended = ", ended_at=now()" if status == "ENDED" else ""
    row = execute_one(
        f"UPDATE state.sessions SET status=%s{ended}, updated_at=now() WHERE id=%s RETURNING *",
        (status, session_id),
    )
    if not row:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(_serialize(row))


@app.route("/api/sessions/<session_id>/pause", methods=["POST"])
def api_session_pause(session_id):
    return _set_session_status(session_id, "PAUSED")


@app.route("/api/sessions/<session_id>/resume", methods=["POST"])
def api_session_resume(session_id):
    return _set_session_status(session_id, "ACTIVE")


@app.route("/api/sessions/<session_id>/end", methods=["POST"])
def api_session_end(session_id):
    return _set_session_status(session_id, "ENDED")


@app.route("/api/campaigns/<campaign_id>/entities", methods=["POST"])
def api_entity_create(campaign_id):
    data = request.get_json(silent=True) or {}
    if not data.get("name") or not data.get("entity_type"):
        return jsonify({"error": "name and entity_type are required"}), 400
    row = _create_entity_record(campaign_id, data)
    return jsonify(_serialize(row)), 201


@app.route("/api/entities/<entity_id>", methods=["PUT"])
def api_entity_update(entity_id):
    from shared.db.connection import execute_one

    data = request.get_json(silent=True) or {}
    fields, params = [], []
    for key in ("name", "tags", "public_sheet", "secret_sheet", "hp_current", "hp_max", "ac", "speed"):
        if key in data:
            fields.append(f"{key}=%s")
            val = json.dumps(data[key]) if key in {"public_sheet", "secret_sheet"} else data[key]
            params.append(val)
    if not fields:
        return jsonify({"error": "no fields provided"}), 400
    params.append(entity_id)
    row = execute_one(
        f"UPDATE state.entities SET {', '.join(fields)}, updated_at=now() WHERE id=%s RETURNING *",
        tuple(params),
    )
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_serialize(row))


@app.route("/api/entities/<entity_id>/control", methods=["POST"])
def api_entity_control(entity_id):
    from shared.db.connection import execute_one

    data = request.get_json(silent=True) or {}
    if data.get("controlled_by") not in {"HUMAN", "AI"}:
        return jsonify({"error": "controlled_by must be HUMAN or AI"}), 400
    row = execute_one(
        """
        UPDATE state.entities
        SET controlled_by=%s, controller_principal_id=%s, control_version=control_version+1, updated_at=now()
        WHERE id=%s RETURNING *
        """,
        (data["controlled_by"], data.get("controller_principal_id"), entity_id),
    )
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_serialize(row))


@app.route("/api/entities/<entity_id>", methods=["DELETE"])
def api_entity_delete(entity_id):
    """Soft delete (tombstone) an entity"""
    from shared.db.connection import execute_one

    row = execute_one(
        """
        UPDATE state.entities
        SET status = 'TOMBSTONED', updated_at = now()
        WHERE id = %s AND status = 'ACTIVE'
        RETURNING *
        """,
        (entity_id,),
    )
    if not row:
        return jsonify({"error": "Not found or already deleted"}), 404
    return jsonify({"success": True, "entity": _serialize(row)})


@app.route("/api/entities/<entity_id>/restore", methods=["POST"])
def api_entity_restore(entity_id):
    """Restore a tombstoned entity"""
    from shared.db.connection import execute_one

    row = execute_one(
        """
        UPDATE state.entities
        SET status = 'ACTIVE', updated_at = now()
        WHERE id = %s AND status = 'TOMBSTONED'
        RETURNING *
        """,
        (entity_id,),
    )
    if not row:
        return jsonify({"error": "Not found or not tombstoned"}), 404
    return jsonify(_serialize(row))


@app.route("/api/entities/<entity_id>/image", methods=["POST"])
def api_entity_image_upload(entity_id):
    """Upload an image for entity portrait"""
    from shared.db.connection import execute_one
    import base64

    # Check if entity exists
    entity = execute_one("SELECT id FROM state.entities WHERE id = %s", (entity_id,))
    if not entity:
        return jsonify({"error": "Entity not found"}), 404

    # Handle file upload
    if "file" in request.files:
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        # Validate file type
        allowed_extensions = {"png", "jpg", "jpeg", "gif", "webp"}
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in allowed_extensions:
            return jsonify({"error": f"Invalid file type. Allowed: {allowed_extensions}"}), 400

        # Read and encode as base64 data URL
        content = file.read()
        if len(content) > 2 * 1024 * 1024:  # 2MB limit
            return jsonify({"error": "File too large. Max 2MB"}), 400

        mime_type = f"image/{ext}" if ext != "jpg" else "image/jpeg"
        data_url = f"data:{mime_type};base64,{base64.b64encode(content).decode()}"

        row = execute_one(
            "UPDATE state.entities SET image_url = %s, updated_at = now() WHERE id = %s RETURNING *",
            (data_url, entity_id),
        )
        return jsonify(_serialize(row))

    # Handle URL-based image
    data = request.get_json(silent=True) or {}
    if data.get("image_url"):
        row = execute_one(
            "UPDATE state.entities SET image_url = %s, updated_at = now() WHERE id = %s RETURNING *",
            (data["image_url"], entity_id),
        )
        return jsonify(_serialize(row))

    return jsonify({"error": "No image provided"}), 400


@app.route("/api/entities/<entity_id>/image", methods=["DELETE"])
def api_entity_image_delete(entity_id):
    """Remove entity portrait"""
    from shared.db.connection import execute_one

    row = execute_one(
        "UPDATE state.entities SET image_url = NULL, updated_at = now() WHERE id = %s RETURNING *",
        (entity_id,),
    )
    if not row:
        return jsonify({"error": "Entity not found"}), 404
    return jsonify(_serialize(row))


# ==================== Session Characters Management ====================


@app.route("/api/sessions/<session_id>/characters")
def api_session_characters(session_id):
    """Get all characters in a session with their status"""
    from shared.db.connection import execute_query

    rows = execute_query(
        """
        SELECT
            sc.id as session_char_id,
            sc.status as session_status,
            sc.joined_at,
            sc.left_at,
            sc.death_round,
            sc.death_details,
            sc.revived_at,
            e.*
        FROM state.session_characters sc
        JOIN state.entities e ON sc.entity_id = e.id
        WHERE sc.session_id = %s
        ORDER BY sc.joined_at
        """,
        (session_id,),
    )
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/sessions/<session_id>/characters", methods=["POST"])
def api_session_character_add(session_id):
    """Add a character to a session"""
    from shared.db.connection import execute_one, execute_query

    data = request.get_json(silent=True) or {}
    entity_id = data.get("entity_id")
    if not entity_id:
        return jsonify({"error": "entity_id required"}), 400

    # Check if session exists and get campaign_id
    session = execute_one(
        "SELECT id, campaign_id FROM state.sessions WHERE id = %s",
        (session_id,),
    )
    if not session:
        return jsonify({"error": "Session not found"}), 404

    # Check if entity exists and belongs to this campaign
    entity = execute_one(
        "SELECT id, name, campaign_id FROM state.entities WHERE id = %s AND status = 'ACTIVE'",
        (entity_id,),
    )
    if not entity:
        return jsonify({"error": "Entity not found or inactive"}), 404
    if str(entity["campaign_id"]) != str(session["campaign_id"]):
        return jsonify({"error": "Entity does not belong to this campaign"}), 400

    # Check if entity has unrevived deaths in this campaign
    deaths = execute_query(
        """
        SELECT id FROM state.entity_death_history
        WHERE entity_id = %s AND campaign_id = %s AND is_revived = FALSE
        """,
        (entity_id, session["campaign_id"]),
    )
    if deaths:
        return jsonify({
            "error": "Character has died in this campaign and must be revived before joining a new session",
            "can_revive": True,
        }), 400

    # Check if already in session
    existing = execute_one(
        "SELECT id, status FROM state.session_characters WHERE session_id = %s AND entity_id = %s",
        (session_id, entity_id),
    )
    if existing:
        if existing["status"] == "ACTIVE":
            return jsonify({"error": "Character already in session"}), 400
        # Reactivate if previously removed
        row = execute_one(
            """
            UPDATE state.session_characters
            SET status = 'ACTIVE', left_at = NULL, updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (existing["id"],),
        )
        return jsonify(_serialize(row))

    # Add to session
    row = execute_one(
        """
        INSERT INTO state.session_characters (session_id, entity_id, status)
        VALUES (%s, %s, 'ACTIVE')
        RETURNING *
        """,
        (session_id, entity_id),
    )
    return jsonify(_serialize(row)), 201


@app.route("/api/sessions/<session_id>/characters/<entity_id>", methods=["PUT"])
def api_session_character_update(session_id, entity_id):
    """Update character status in session (mark as dead, removed, etc.)"""
    from shared.db.connection import execute_one

    data = request.get_json(silent=True) or {}
    new_status = data.get("status")
    if new_status not in {"ACTIVE", "DEAD", "REMOVED", "RETIRED"}:
        return jsonify({"error": "Invalid status"}), 400

    # Get current record
    current = execute_one(
        "SELECT * FROM state.session_characters WHERE session_id = %s AND entity_id = %s",
        (session_id, entity_id),
    )
    if not current:
        return jsonify({"error": "Character not in session"}), 404

    # Handle death
    if new_status == "DEAD" and current["status"] != "DEAD":
        # Record death in history
        session = execute_one("SELECT campaign_id FROM state.sessions WHERE id = %s", (session_id,))
        execute_one(
            """
            INSERT INTO state.entity_death_history
                (entity_id, campaign_id, session_id, death_type, death_details)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                entity_id,
                session["campaign_id"],
                session_id,
                data.get("death_type", "OTHER"),
                json.dumps(data.get("death_details", {})),
            ),
        )

    # Update session character record
    row = execute_one(
        """
        UPDATE state.session_characters
        SET status = %s,
            death_round = %s,
            death_details = %s,
            left_at = CASE WHEN %s IN ('REMOVED', 'RETIRED') THEN now() ELSE left_at END,
            updated_at = now()
        WHERE session_id = %s AND entity_id = %s
        RETURNING *
        """,
        (
            new_status,
            data.get("death_round"),
            json.dumps(data.get("death_details", {})) if data.get("death_details") else None,
            new_status,
            session_id,
            entity_id,
        ),
    )
    return jsonify(_serialize(row))


@app.route("/api/sessions/<session_id>/characters/<entity_id>/revive", methods=["POST"])
def api_session_character_revive(session_id, entity_id):
    """Revive a dead character"""
    from shared.db.connection import execute_one

    data = request.get_json(silent=True) or {}
    revive_method = data.get("method", "STORY")  # SPELL, DIVINE_INTERVENTION, STORY, etc.

    # Check current status
    current = execute_one(
        "SELECT * FROM state.session_characters WHERE session_id = %s AND entity_id = %s",
        (session_id, entity_id),
    )
    if not current:
        return jsonify({"error": "Character not in session"}), 404
    if current["status"] != "DEAD":
        return jsonify({"error": "Character is not dead"}), 400

    # Get session for campaign_id
    session = execute_one("SELECT campaign_id FROM state.sessions WHERE id = %s", (session_id,))

    # Update death history to mark as revived
    execute_one(
        """
        UPDATE state.entity_death_history
        SET is_revived = TRUE,
            revived_in_session_id = %s,
            revive_method = %s,
            revive_details = %s,
            revived_at = now()
        WHERE entity_id = %s
          AND campaign_id = %s
          AND is_revived = FALSE
        """,
        (
            session_id,
            revive_method,
            json.dumps(data.get("revive_details", {})),
            entity_id,
            session["campaign_id"],
        ),
    )

    # Update session character
    row = execute_one(
        """
        UPDATE state.session_characters
        SET status = 'ACTIVE',
            revived_at = now(),
            revive_details = %s,
            updated_at = now()
        WHERE session_id = %s AND entity_id = %s
        RETURNING *
        """,
        (json.dumps(data.get("revive_details", {})), session_id, entity_id),
    )

    # Restore entity HP to 1 (or specified amount)
    restore_hp = data.get("restore_hp", 1)
    execute_one(
        "UPDATE state.entities SET hp_current = LEAST(%s, hp_max), updated_at = now() WHERE id = %s",
        (restore_hp, entity_id),
    )

    return jsonify(_serialize(row))


@app.route("/api/sessions/<session_id>/characters/<entity_id>", methods=["DELETE"])
def api_session_character_remove(session_id, entity_id):
    """Remove a character from a session"""
    from shared.db.connection import execute_one

    row = execute_one(
        """
        UPDATE state.session_characters
        SET status = 'REMOVED', left_at = now(), updated_at = now()
        WHERE session_id = %s AND entity_id = %s AND status = 'ACTIVE'
        RETURNING *
        """,
        (session_id, entity_id),
    )
    if not row:
        return jsonify({"error": "Character not in session or already removed"}), 404
    return jsonify({"success": True, "record": _serialize(row)})


@app.route("/api/campaigns/<campaign_id>/available_characters")
def api_available_characters(campaign_id):
    """Get characters available to join sessions (not permanently dead)"""
    from shared.db.connection import execute_query

    rows = execute_query(
        """
        SELECT e.*,
            CASE WHEN EXISTS (
                SELECT 1 FROM state.entity_death_history edh
                WHERE edh.entity_id = e.id
                  AND edh.campaign_id = %s
                  AND edh.is_revived = FALSE
            ) THEN TRUE ELSE FALSE END as is_dead_in_campaign
        FROM state.entities e
        WHERE e.campaign_id = %s
          AND e.status = 'ACTIVE'
          AND e.entity_type IN ('PC', 'NPC')
        ORDER BY e.name
        """,
        (campaign_id, campaign_id),
    )
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/campaigns/<campaign_id>/characters/generate", methods=["POST"])
def api_generate_character(campaign_id):
    from services.llm.adapter import LLMAdapter

    data = request.get_json(silent=True) or {}
    concept = data.get("concept", "A balanced adventurer")
    populate_form = data.get("populate_form", False)

    # Enhanced schema with full character sheet structure
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "entity_type": {"type": "string", "enum": ["PC", "NPC"]},
            "controlled_by": {"type": "string", "enum": ["PLAYER", "AI_NPC", "GM"]},
            "hp_max": {"type": "integer", "minimum": 1},
            "public_sheet": {
                "type": "object",
                "properties": {
                    "race": {"type": "string"},
                    "class": {"type": "string"},
                    "level": {"type": "integer", "minimum": 1, "maximum": 20},
                    "background": {"type": "string"},
                    "attributes": {
                        "type": "object",
                        "properties": {
                            "strength": {"type": "integer", "minimum": 1, "maximum": 30},
                            "dexterity": {"type": "integer", "minimum": 1, "maximum": 30},
                            "constitution": {"type": "integer", "minimum": 1, "maximum": 30},
                            "intelligence": {"type": "integer", "minimum": 1, "maximum": 30},
                            "wisdom": {"type": "integer", "minimum": 1, "maximum": 30},
                            "charisma": {"type": "integer", "minimum": 1, "maximum": 30},
                        },
                        "required": ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"],
                        "additionalProperties": False,
                    },
                    "armor_class": {"type": "integer", "minimum": 1},
                    "speed": {"type": "integer", "minimum": 0},
                    "initiative_bonus": {"type": "integer"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "languages": {"type": "array", "items": {"type": "string"}},
                    "abilities": {"type": "string"},
                    "actions": {"type": "string"},
                    "weapons": {"type": "string"},
                    "armor": {"type": "string"},
                    "equipment": {"type": "string"},
                    "gold": {"type": "integer", "minimum": 0},
                    "personality": {
                        "type": "object",
                        "properties": {
                            "traits": {"type": "string"},
                            "ideals": {"type": "string"},
                            "bonds": {"type": "string"},
                            "flaws": {"type": "string"},
                            "goals": {"type": "string"},
                        },
                        "required": ["traits", "ideals", "bonds", "flaws", "goals"],
                        "additionalProperties": False,
                    },
                    "backstory": {"type": "string"},
                    "allies": {"type": "string"},
                    "enemies": {"type": "string"},
                },
                "required": ["race", "class", "level", "background", "attributes", "armor_class", "speed", "skills", "languages", "personality", "backstory"],
                "additionalProperties": False,
            },
            "secret_sheet": {
                "type": "object",
                "properties": {
                    "secrets": {"type": "string"},
                    "plot_hooks": {"type": "string"},
                    "balance_notes": {"type": "string"},
                },
                "required": ["secrets", "plot_hooks", "balance_notes"],
                "additionalProperties": False,
            },
            "tags": {"type": "array", "items": {"type": "string"}},
            "ac": {"type": "integer", "minimum": 1},
            "speed": {"type": "integer", "minimum": 0},
        },
        "required": ["name", "entity_type", "controlled_by", "hp_max", "public_sheet", "secret_sheet", "tags", "ac", "speed"],
        "additionalProperties": False,
    }

    system_prompt = """You are a tabletop RPG character generator. Create detailed, balanced characters with interesting backstories and personalities.
Generate realistic stats (typically 8-18 for attributes), appropriate equipment for the class and level, and compelling personality traits.
Make the character feel like a real person with motivations, flaws, and connections to the world."""

    user_prompt = f"""Generate a complete character based on this concept: {concept}

Guidelines:
- Use standard fantasy RPG conventions (D&D-style)
- Attributes should follow 4d6-drop-lowest distribution (typically 8-18)
- HP should be appropriate for class and level (e.g., level 1 fighter: 10-12 HP)
- AC (armor class) should be 10-18 depending on armor worn
- Speed is typically 30 for medium creatures
- Include 2-4 proficient skills appropriate to the class
- Create a compelling but concise backstory (2-3 sentences)
- Add interesting personality traits, ideals, bonds, and flaws
- Include at least one secret or plot hook for the DM
- Equipment should be appropriate for a starting character of that class
- Note: ac and speed must be at the TOP LEVEL of the JSON, not inside public_sheet"""

    llm = LLMAdapter(model="gpt-4o-mini", campaign_id=uuid.UUID(campaign_id), role="dm")
    generated = llm.generate_structured(system_prompt, user_prompt, response_schema=schema)

    if generated.get("error"):
        return jsonify(generated), 400

    # Add derived fields
    generated["hp_current"] = generated["hp_max"]
    sheet = generated.get("public_sheet", {})
    sheet["x"] = 0
    sheet["y"] = 0

    # If populate_form is true, return the character without saving
    if populate_form:
        return jsonify({"character": generated, "message": "Character generated. Review and create."}), 200

    # Otherwise create the entity in the database
    created = _create_entity_record(campaign_id, generated)
    return jsonify(_serialize(created)), 201


@app.route("/api/campaigns/<campaign_id>/ai_config")
def api_ai_config_get(campaign_id):
    return jsonify(_get_ai_config(campaign_id))


@app.route("/api/campaigns/<campaign_id>/ai_config", methods=["PUT"])
def api_ai_config_put(campaign_id):
    from shared.db.connection import execute_one
    from services.llm.adapter import resolve_provider_base_url, SUPPORTED_PROVIDERS

    data = request.get_json(silent=True) or {}
    provider = (data.get("llm_provider") or "mock").lower()
    if provider not in SUPPORTED_PROVIDERS:
        return jsonify({"error": f"invalid provider — supported: {sorted(SUPPORTED_PROVIDERS)}"}), 400

    # API keys + image-gen config live in the settings JSONB so we don't need
    # a migration every time we add a provider. Each key is namespaced by
    # provider so a campaign can store keys for multiple at once.
    incoming_settings = data.get("settings") or {}
    # Merge with existing settings so callers can update one field at a time.
    existing = execute_one(
        "SELECT settings FROM state.campaign_settings WHERE campaign_id=%s",
        (campaign_id,),
    )
    merged_settings = dict((existing or {}).get("settings") or {})
    for k, v in incoming_settings.items():
        merged_settings[k] = v
    # Top-level api_key field is a convenience alias for the active provider's key.
    if "api_key" in data:
        merged_settings.setdefault("api_keys", {})[provider] = data["api_key"]

    row = execute_one(
        """
        INSERT INTO state.campaign_settings (campaign_id,llm_provider,llm_base_url,embedding_base_url,dm_model,npc_model,embedding_model,settings,updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())
        ON CONFLICT (campaign_id) DO UPDATE
        SET llm_provider=EXCLUDED.llm_provider,
            llm_base_url=EXCLUDED.llm_base_url,
            embedding_base_url=EXCLUDED.embedding_base_url,
            dm_model=EXCLUDED.dm_model,
            npc_model=EXCLUDED.npc_model,
            embedding_model=EXCLUDED.embedding_model,
            settings=EXCLUDED.settings,
            updated_at=now()
        RETURNING *
        """,
        (
            campaign_id,
            provider,
            resolve_provider_base_url(provider, data.get("llm_base_url")),
            resolve_provider_base_url(provider, data.get("embedding_base_url") or data.get("llm_base_url")),
            data.get("dm_model", "gpt-4o-mini"),
            data.get("npc_model", "gpt-4o-mini"),
            data.get("embedding_model", "text-embedding-3-small"),
            json.dumps(merged_settings),
        ),
    )
    return jsonify(_serialize(row))


@app.route("/api/ai/models")
def api_ai_models():
    provider = request.args.get("provider", "mock")
    base_url = request.args.get("base_url") or None  # Convert empty string to None
    if provider == "mock":
        return jsonify({"data": [{"id": "mock-model"}]})
    try:
        client = _openai_client_for(provider, base_url)
        models = client.models.list()
        return jsonify({"data": [{"id": m.id} for m in models.data]})
    except Exception as e:
        error_msg = str(e)
        if "Connection refused" in error_msg or "connect" in error_msg.lower():
            return jsonify({
                "error": f"Cannot connect to {provider}. Is it running?",
                "detail": error_msg,
                "hint": f"Start {provider} and try again."
            }), 503
        return jsonify({"error": error_msg}), 500


@app.route("/api/ai/test_provider", methods=["POST"])
def api_ai_test_provider():
    data = request.get_json(silent=True) or {}
    provider = data.get("provider", "mock")
    base_url = data.get("base_url") or None  # Convert empty string to None
    model = data.get("model") or "gpt-4o-mini"
    if provider == "mock":
        return jsonify({"ok": True, "models": ["mock-model"], "completion": "mock ok"})
    try:
        client = _openai_client_for(provider, base_url)
        # First try to list models
        try:
            models = client.models.list()
            model_list = [m.id for m in models.data]
        except Exception:
            model_list = ["(unable to list models)"]

        # Try a simple completion
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with: ok"}],
            temperature=0,
            max_tokens=10,
        )
        return jsonify({
            "ok": True,
            "models": model_list,
            "completion": completion.choices[0].message.content,
        })
    except Exception as e:
        error_msg = str(e)
        if "Connection refused" in error_msg or "connect" in error_msg.lower():
            return jsonify({
                "ok": False,
                "error": f"Cannot connect to {provider}. Is it running?",
                "detail": error_msg,
                "hint": f"Start {provider} at the expected URL and try again."
            }), 503
        if "model" in error_msg.lower() and "not found" in error_msg.lower():
            return jsonify({
                "ok": False,
                "error": f"Model '{model}' not found",
                "detail": error_msg,
                "hint": "Check the model name or use 'List Models' to see available models."
            }), 400
        return jsonify({"ok": False, "error": error_msg}), 500


_LOCAL_PROVIDER_DEFAULTS = {
    # Use 127.0.0.1 (not "localhost") for the probe to avoid IPv6 dual-stack
    # latency on Windows where ``localhost`` resolves to ``::1`` first and the
    # IPv6 connection attempt blocks before falling back to IPv4.
    "ollama": "http://127.0.0.1:11434/v1",
    "lmstudio": "http://127.0.0.1:1234/v1",
}


@app.route("/api/ai/detect_local")
def api_ai_detect_local():
    """Lightweight probe for a local OpenAI-compatible server (default: LM Studio).

    Bypasses the OpenAI SDK and any heavy imports so the round-trip stays in
    the tens of ms when the server is up and fails fast (connection refused)
    when it isn't. Always returns 200; clients inspect ``detected``.
    """
    provider = (request.args.get("provider") or "lmstudio").lower()
    base_url = (request.args.get("base_url") or _LOCAL_PROVIDER_DEFAULTS.get(provider) or "").strip()
    canonical_base_url = base_url
    # If the caller forced a base_url containing "localhost", swap to 127.0.0.1
    # for the probe only (the canonical URL we report back is unchanged so it
    # round-trips into ai_config the way the user expects).
    probe_base = base_url.replace("//localhost:", "//127.0.0.1:") if base_url else ""
    if not probe_base:
        return jsonify({
            "detected": False, "provider": provider,
            "base_url": None, "error": "no default base_url for provider",
        })
    models_url = probe_base.rstrip("/") + "/models"
    try:
        req = urllib_request.Request(models_url, headers={"Accept": "application/json"})
        with urllib_request.urlopen(req, timeout=1.5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(body) if body else {}
        raw = payload.get("data") if isinstance(payload, dict) else None
        models = [{"id": m.get("id")} for m in raw if isinstance(m, dict) and m.get("id")] if isinstance(raw, list) else []
        return jsonify({
            "detected": len(models) > 0,
            "provider": provider,
            "base_url": canonical_base_url,
            "models": models,
        })
    except urllib_error.URLError as e:
        return jsonify({
            "detected": False, "provider": provider,
            "base_url": canonical_base_url, "error": str(getattr(e, "reason", e)),
        })
    except (TimeoutError, socket.timeout):
        return jsonify({
            "detected": False, "provider": provider,
            "base_url": canonical_base_url, "error": "timeout",
        })
    except Exception as e:
        return jsonify({
            "detected": False, "provider": provider,
            "base_url": canonical_base_url, "error": str(e),
        })


@app.route("/api/campaigns/<campaign_id>/rag/upload", methods=["POST"])
def api_rag_upload(campaign_id):
    from shared.db.connection import execute_one

    if "file" not in request.files:
        return jsonify({"error": "file is required"}), 400
    upload = request.files["file"]
    if not upload.filename:
        return jsonify({"error": "empty filename"}), 400

    safe_filename = secure_filename(upload.filename)
    if not safe_filename:
        return jsonify({"error": "invalid filename"}), 400

    row = execute_one(
        """
        INSERT INTO state.rag_documents (campaign_id, filename, storage_path, status)
        VALUES (%s, %s, %s, 'QUEUED')
        RETURNING *
        """,
        (campaign_id, safe_filename, "pending"),
    )
    doc_id = str(row["id"])
    base_dir = (Path("data/rag") / campaign_id / doc_id).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    dest = (base_dir / safe_filename).resolve()
    if base_dir not in dest.parents:
        return jsonify({"error": "invalid upload path"}), 400
    upload.save(dest)

    queued = execute_one(
        "UPDATE state.rag_documents SET storage_path=%s, status='QUEUED', updated_at=now() WHERE id=%s RETURNING *",
        (str(dest), doc_id),
    )
    _queue_rag_processing(doc_id)
    return jsonify(_serialize(queued)), 202


@app.route("/api/campaigns/<campaign_id>/rag/documents")
def api_rag_documents(campaign_id):
    from shared.db.connection import execute_query

    rows = execute_query(
        "SELECT * FROM state.rag_documents WHERE campaign_id=%s ORDER BY created_at DESC",
        (campaign_id,),
    )
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/rag/documents/<doc_id>/enable", methods=["POST"])
def api_rag_enable(doc_id):
    from shared.db.connection import execute_one
    return jsonify(_serialize(execute_one("UPDATE state.rag_documents SET enabled=true, updated_at=now() WHERE id=%s RETURNING *", (doc_id,))))


@app.route("/api/rag/documents/<doc_id>/disable", methods=["POST"])
def api_rag_disable(doc_id):
    from shared.db.connection import execute_one
    return jsonify(_serialize(execute_one("UPDATE state.rag_documents SET enabled=false, updated_at=now() WHERE id=%s RETURNING *", (doc_id,))))


@app.route("/api/rag/documents/<doc_id>/reindex", methods=["POST"])
def api_rag_reindex(doc_id):
    from shared.db.connection import execute_one
    doc = execute_one("SELECT campaign_id FROM state.rag_documents WHERE id=%s", (doc_id,))
    if not doc:
        return jsonify({"error": "Not found"}), 404
    execute_one(
        "UPDATE state.rag_documents SET status='QUEUED', error_text=NULL, updated_at=now() WHERE id=%s RETURNING id",
        (doc_id,),
    )
    _queue_rag_processing(doc_id)
    return jsonify({"status": "queued", "doc_id": doc_id})


@app.route("/api/campaigns/<campaign_id>/rag/query", methods=["POST"])
def api_rag_query(campaign_id):
    from services.llm.adapter import LLMAdapter

    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400
    top_k = int(data.get("top_k", 5))
    try:
        llm = LLMAdapter(campaign_id=uuid.UUID(campaign_id), role="dm")
        embedding = llm.embed_texts([query])
        query_vector = embedding["vectors"][0] if embedding["vectors"] else []
        if not query_vector:
            return jsonify({"results": []})

        hits = _search_qdrant(campaign_id, query_vector, top_k)
        results = []
        for hit in hits:
            payload = hit.get("payload", {})
            results.append(
                {
                    "score": hit.get("score"),
                    "doc_id": payload.get("doc_id"),
                    "chunk_id": payload.get("chunk_id"),
                    "page": payload.get("page"),
                    "filename": payload.get("source_filename"),
                    "text": payload.get("text"),
                    "metadata": {
                        "campaign_id": payload.get("campaign_id"),
                        "source_filename": payload.get("source_filename"),
                    },
                }
            )
        return jsonify({"results": results})
    except RuntimeError as exc:
        if "404" in str(exc):
            return jsonify({"results": []})
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@socketio.on("connect")
def handle_connect():
    emit("connected", {"status": "ok"})


@socketio.on("join_campaign")
def handle_join_campaign(data):
    campaign_id = data.get("campaign_id")
    if campaign_id:
        join_room(str(campaign_id))
        emit("joined", {"campaign_id": campaign_id})


@socketio.on("leave_campaign")
def handle_leave_campaign(data):
    campaign_id = data.get("campaign_id")
    if campaign_id:
        leave_room(str(campaign_id))


@socketio.on("submit_intent")
def handle_submit_intent(data):
    try:
        from shared.schemas.contracts import InterventionProposal
        from shared.auth.principal import load_principal
        from services.orchestrator.pipeline import OrchestratorPipeline

        proposal = InterventionProposal(
            action_type=data["action_type"],
            params=data.get("params", {}),
            proposer_principal_id=uuid.UUID(data["principal_id"]),
            campaign_id=uuid.UUID(data["campaign_id"]),
            session_id=uuid.UUID(
                data.get("session_id", "66666666-6666-6666-6666-666666666661")
            ),
            encounter_id=uuid.UUID(data["encounter_id"])
            if data.get("encounter_id")
            else None,
            idempotency_key=data.get("idempotency_key"),
        )

        principal = load_principal(proposal.proposer_principal_id, proposal.campaign_id)
        if not principal:
            emit("error", {"message": "Principal not found"})
            return

        pipeline = OrchestratorPipeline()
        result = pipeline.process_proposal(proposal, principal, proposal.session_id)

        emit("game_event", result, room=str(proposal.campaign_id))

    except Exception as e:
        emit("error", {"message": str(e)})


# =============================================================================
# Story State Board Endpoints
# =============================================================================


@app.route("/api/sessions/<session_id>/story_state")
def api_get_story_state(session_id):
    """Get the current story state for a session"""
    from shared.db.connection import execute_one

    row = execute_one(
        """
        SELECT ss.*, s.id as session_id, s.status as session_status
        FROM state.story_state ss
        JOIN state.sessions s ON ss.session_id = s.id
        WHERE ss.session_id = %s
        """,
        (session_id,),
    )
    if not row:
        return jsonify({"error": "Story state not found"}), 404
    return jsonify(_serialize(row))


@app.route("/api/sessions/<session_id>/story_state", methods=["PUT"])
def api_update_story_state(session_id):
    """Update the story state for a session"""
    from shared.db.connection import execute_one, transaction

    data = request.get_json(silent=True) or {}

    with transaction() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get existing story state
        cur.execute("SELECT * FROM state.story_state WHERE session_id = %s", (session_id,))
        existing = cur.fetchone()
        if not existing:
            return jsonify({"error": "Story state not found"}), 404

        # Build update query dynamically
        allowed_fields = [
            "current_location", "location_details", "game_time", "game_time_details",
            "active_npcs", "party_status", "active_quests", "recent_events",
            "plot_threads", "party_goals", "key_items", "party_resources",
            "dm_notes", "dm_private_notes"
        ]
        updates = []
        values = []
        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                val = data[field]
                if isinstance(val, (dict, list)):
                    values.append(json.dumps(val))
                else:
                    values.append(val)

        if not updates:
            return jsonify({"error": "No valid fields to update"}), 400

        updates.append("updated_at = now()")
        if data.get("updated_by"):
            updates.append("updated_by = %s")
            values.append(data["updated_by"])

        values.append(session_id)
        cur.execute(
            f"UPDATE state.story_state SET {', '.join(updates)} WHERE session_id = %s RETURNING *",
            values,
        )
        updated = cur.fetchone()

        # Log change to history
        change_type = data.get("change_type", "OTHER")
        cur.execute(
            """
            INSERT INTO state.story_state_history
            (story_state_id, session_id, state_snapshot, change_type, change_description, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                str(updated["id"]),
                session_id,
                json.dumps(_serialize(updated)),
                change_type,
                data.get("change_description", ""),
                data.get("updated_by"),
            ),
        )

    return jsonify(_serialize(updated))


@app.route("/api/sessions/<session_id>/story_state/history")
def api_story_state_history(session_id):
    """Get history of story state changes for a session"""
    from shared.db.connection import execute_query

    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    rows = execute_query(
        """
        SELECT ssh.*, p.display_name as updated_by_name
        FROM state.story_state_history ssh
        LEFT JOIN state.principals p ON ssh.created_by = p.id
        WHERE ssh.session_id = %s
        ORDER BY ssh.created_at DESC
        LIMIT %s OFFSET %s
        """,
        (session_id, limit, offset),
    )
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/sessions/<session_id>/story_state/add_event", methods=["POST"])
def api_add_story_event(session_id):
    """Add a new event to the story state recent_events"""
    from shared.db.connection import execute_one
    from datetime import datetime

    data = request.get_json(silent=True) or {}
    description = data.get("description", "").strip()
    if not description:
        return jsonify({"error": "description is required"}), 400

    importance = data.get("importance", "normal")

    # Get current story state
    row = execute_one("SELECT * FROM state.story_state WHERE session_id = %s", (session_id,))
    if not row:
        return jsonify({"error": "Story state not found"}), 404

    # Add event to recent_events array
    recent_events = row.get("recent_events") or []
    new_event = {
        "timestamp": datetime.utcnow().isoformat(),
        "description": description,
        "importance": importance,
    }
    recent_events.append(new_event)

    # Keep only last 100 events
    recent_events = recent_events[-100:]

    updated = execute_one(
        """
        UPDATE state.story_state
        SET recent_events = %s, updated_at = now()
        WHERE session_id = %s
        RETURNING *
        """,
        (json.dumps(recent_events), session_id),
    )
    return jsonify(_serialize(updated))


# =============================================================================
# Session Archive and History Endpoints
# =============================================================================


@app.route("/api/campaigns/<campaign_id>/session_archives")
def api_session_archives(campaign_id):
    """Get archived sessions for a campaign"""
    from shared.db.connection import execute_query

    rows = execute_query(
        """
        SELECT id, original_session_id, campaign_id, session_name, session_number,
               started_at, ended_at, session_summary, archived_at, archive_reason,
               jsonb_array_length(COALESCE(chat_history, '[]'::jsonb)) as chat_count
        FROM state.session_archives
        WHERE campaign_id = %s
        ORDER BY archived_at DESC
        """,
        (campaign_id,),
    )
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/session_archives/<archive_id>")
def api_session_archive_detail(archive_id):
    """Get full details of an archived session including chat history"""
    from shared.db.connection import execute_one

    row = execute_one(
        "SELECT * FROM state.session_archives WHERE id = %s",
        (archive_id,),
    )
    if not row:
        return jsonify({"error": "Archive not found"}), 404
    return jsonify(_serialize(row))


@app.route("/api/session_archives/<archive_id>", methods=["DELETE"])
def api_delete_session_archive(archive_id):
    """Permanently delete an archived session"""
    from shared.db.connection import execute_one

    row = execute_one(
        "DELETE FROM state.session_archives WHERE id = %s RETURNING id",
        (archive_id,),
    )
    if not row:
        return jsonify({"error": "Archive not found"}), 404
    return jsonify({"success": True, "deleted_id": str(row["id"])})


@app.route("/api/sessions/<session_id>/chat_history")
def api_session_chat_history(session_id):
    """Get chat history for a session from ledger events"""
    from shared.db.connection import execute_query

    limit = request.args.get("limit", 100, type=int)
    before_seq = request.args.get("before_seq")

    base_query = """
        SELECT sl.seq_id, sl.event_id, sl.type as event_type, sl.payload,
               sl.sender_principal_id as principal_id, sl.sender_entity_id,
               sl.created_at, e.name as speaker_name, p.display_name as principal_name
        FROM ledger.session_ledger sl
        LEFT JOIN state.entities e ON sl.sender_entity_id = e.id
        LEFT JOIN state.principals p ON sl.sender_principal_id = p.id
        WHERE sl.session_id = %s
          AND sl.type IN ('CHAT', 'ACTION', 'NARRATION', 'SYSTEM', 'GM_WHISPER')
    """

    if before_seq:
        query = base_query + " AND sl.seq_id < %s ORDER BY sl.seq_id DESC LIMIT %s"
        rows = execute_query(query, (session_id, int(before_seq), limit))
    else:
        query = base_query + " ORDER BY sl.seq_id DESC LIMIT %s"
        rows = execute_query(query, (session_id, limit))

    # Return in chronological order
    return jsonify(list(reversed([_serialize(r) for r in rows])))


@app.route("/api/sessions/<session_id>/resume_data")
def api_session_resume_data(session_id):
    """Get session state for resuming play - returns story state and recent chat"""
    from shared.db.connection import execute_query, execute_one

    # Get session info
    session = execute_one(
        """
        SELECT s.*, c.name as campaign_name
        FROM state.sessions s
        JOIN state.campaigns c ON s.campaign_id = c.id
        WHERE s.id = %s
        """,
        (session_id,),
    )
    if not session:
        return jsonify({"error": "Session not found"}), 404

    # Get story state
    story_state = execute_one(
        "SELECT * FROM state.story_state WHERE session_id = %s",
        (session_id,),
    )

    # Get recent chat (last 50 messages)
    chat_history = execute_query(
        """
        SELECT sl.seq_id, sl.event_id, sl.type as event_type, sl.payload,
               sl.sender_principal_id as principal_id, sl.sender_entity_id,
               sl.created_at, e.name as speaker_name, p.display_name as principal_name
        FROM ledger.session_ledger sl
        LEFT JOIN state.entities e ON sl.sender_entity_id = e.id
        LEFT JOIN state.principals p ON sl.sender_principal_id = p.id
        WHERE sl.session_id = %s
          AND sl.type IN ('CHAT', 'ACTION', 'NARRATION', 'SYSTEM', 'GM_WHISPER')
        ORDER BY sl.seq_id DESC
        LIMIT 50
        """,
        (session_id,),
    )

    # Get party members
    party = execute_query(
        """
        SELECT sc.*, e.name, e.hp_current, e.hp_max, e.image_url,
               e.public_sheet
        FROM state.session_characters sc
        JOIN state.entities e ON sc.entity_id = e.id
        WHERE sc.session_id = %s AND sc.status IN ('ACTIVE', 'DEAD')
        ORDER BY e.name
        """,
        (session_id,),
    )

    return jsonify({
        "session": _serialize(session),
        "story_state": _serialize(story_state) if story_state else None,
        "chat_history": list(reversed([_serialize(r) for r in chat_history])),
        "party": [_serialize(r) for r in party],
    })


@app.route("/api/sessions/<session_id>/archive", methods=["POST"])
def api_archive_session(session_id):
    """Manually archive a session (without deleting it)"""
    from shared.db.connection import execute_one, execute_query, transaction

    data = request.get_json(silent=True) or {}

    with transaction() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get session
        cur.execute("SELECT * FROM state.sessions WHERE id = %s", (session_id,))
        session = cur.fetchone()
        if not session:
            return jsonify({"error": "Session not found"}), 404

        # Gather chat history
        cur.execute(
            """
            SELECT sl.created_at, sl.type as event_type, sl.payload, sl.sender_principal_id as principal_id
            FROM ledger.session_ledger sl
            WHERE sl.session_id = %s
              AND sl.type IN ('CHAT', 'ACTION', 'NARRATION', 'SYSTEM')
            ORDER BY sl.created_at
            """,
            (session_id,),
        )
        chat_rows = cur.fetchall()
        chat_history = [_serialize(r) for r in chat_rows]

        # Get story state
        cur.execute("SELECT * FROM state.story_state WHERE session_id = %s", (session_id,))
        story_row = cur.fetchone()
        story_snapshot = _serialize(story_row) if story_row else {}

        # Create archive
        cur.execute(
            """
            INSERT INTO state.session_archives
            (original_session_id, campaign_id, session_name, session_number,
             started_at, ended_at, chat_history, final_story_state,
             session_summary, archive_reason, archived_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                session_id,
                str(session["campaign_id"]),
                session.get("name"),
                session.get("session_number"),
                session.get("started_at"),
                session.get("ended_at"),
                json.dumps(chat_history),
                json.dumps(story_snapshot),
                data.get("summary", ""),
                data.get("reason", "COMPLETED"),
                data.get("archived_by"),
            ),
        )
        archive = cur.fetchone()

        # Mark session as archived
        cur.execute(
            "UPDATE state.sessions SET is_archived = TRUE WHERE id = %s",
            (session_id,),
        )

    return jsonify(_serialize(archive))


def _serialize(obj):
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialize(v) for v in obj]
    elif isinstance(obj, uuid.UUID):
        return str(obj)
    elif hasattr(obj, "isoformat"):
        return obj.isoformat()
    elif isinstance(obj, (bytes, memoryview)):
        return str(bytes(obj))
    return obj


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    socketio.run(app, host="0.0.0.0", port=port, debug=True, allow_unsafe_werkzeug=True)
