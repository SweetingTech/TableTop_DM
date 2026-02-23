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

    cur.execute("SELECT * FROM state.campaigns ORDER BY created_at DESC")
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


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json()
    try:
        from services.conversations.manager import ConversationManager

        cm = ConversationManager()
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

        dm = DMNarrationAgent()
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


@app.route("/api/campaigns/<campaign_id>/purge", methods=["POST"])
def api_campaign_purge(campaign_id):
    from shared.db.connection import execute_one

    row = execute_one(
        "UPDATE state.campaigns SET status='PURGED', updated_at=now() WHERE id=%s RETURNING *",
        (campaign_id,),
    )
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"warning": "PURGE is irreversible", "campaign": _serialize(row)})


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


@app.route("/api/campaigns/<campaign_id>/characters/generate", methods=["POST"])
def api_generate_character(campaign_id):
    from services.llm.adapter import LLMAdapter

    data = request.get_json(silent=True) or {}
    concept = data.get("concept", "A balanced adventurer")
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "entity_type": {"type": "string", "enum": ["PC", "NPC"]},
            "hp_max": {"type": "integer", "minimum": 1},
            "ac": {"type": "integer", "minimum": 1},
            "speed": {"type": "integer", "minimum": 0},
            "public_sheet": {"type": "object"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "entity_type", "hp_max", "ac", "speed", "public_sheet", "tags"],
        "additionalProperties": False,
    }
    llm = LLMAdapter(model="gpt-4o-mini", campaign_id=uuid.UUID(campaign_id), role="dm")
    generated = llm.generate_structured(
        "Generate a JSON tabletop character sheet.",
        f"Concept: {concept}. Keep numeric values modest.",
        response_schema=schema,
    )
    if generated.get("error"):
        return jsonify(generated), 400
    generated["hp_current"] = generated["hp_max"]
    generated["controlled_by"] = "HUMAN"
    created = _create_entity_record(campaign_id, generated)
    return jsonify(_serialize(created)), 201


@app.route("/api/campaigns/<campaign_id>/ai_config")
def api_ai_config_get(campaign_id):
    return jsonify(_get_ai_config(campaign_id))


@app.route("/api/campaigns/<campaign_id>/ai_config", methods=["PUT"])
def api_ai_config_put(campaign_id):
    from shared.db.connection import execute_one
    from services.llm.adapter import resolve_provider_base_url

    data = request.get_json(silent=True) or {}
    provider = (data.get("llm_provider") or "mock").lower()
    if provider not in {"openai", "ollama", "lmstudio", "mock"}:
        return jsonify({"error": "invalid provider"}), 400
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
            json.dumps(data.get("settings", {})),
        ),
    )
    return jsonify(_serialize(row))


@app.route("/api/ai/models")
def api_ai_models():
    provider = request.args.get("provider", "mock")
    base_url = request.args.get("base_url")
    if provider == "mock":
        return jsonify({"data": [{"id": "mock-model"}]})
    client = _openai_client_for(provider, base_url)
    models = client.models.list()
    return jsonify({"data": [{"id": m.id} for m in models.data]})


@app.route("/api/ai/test_provider", methods=["POST"])
def api_ai_test_provider():
    data = request.get_json(silent=True) or {}
    provider = data.get("provider", "mock")
    base_url = data.get("base_url")
    model = data.get("model") or "gpt-4o-mini"
    if provider == "mock":
        return jsonify({"ok": True, "models": ["mock-model"], "completion": "mock ok"})
    client = _openai_client_for(provider, base_url)
    models = client.models.list()
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with: ok"}],
        temperature=0,
        max_tokens=10,
    )
    return jsonify({
        "ok": True,
        "models": [m.id for m in models.data],
        "completion": completion.choices[0].message.content,
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
