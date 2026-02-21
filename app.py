import os
import uuid
import json
import traceback
from flask import Flask, render_template, request, jsonify, Response
from flask_socketio import SocketIO, emit, join_room, leave_room
import psycopg2
import psycopg2.extras

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", os.urandom(32).hex())
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")


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

    return render_template("index.html",
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


@app.route("/api/health")
def health():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return jsonify({"status": "ok", "database": "connected"})
    except Exception as e:
        return jsonify({"status": "error", "database": str(e)}), 500


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
    rows = execute_query("""
        SELECT e.*, p.display_name as controller_name
        FROM state.entities e
        LEFT JOIN state.principals p ON e.controller_principal_id = p.id
        WHERE e.campaign_id = %s ORDER BY e.entity_type, e.name
    """, (campaign_id,))
    return jsonify([_serialize(r) for r in rows])


@app.route("/api/campaigns/<campaign_id>/encounters")
def api_encounters(campaign_id):
    from shared.db.connection import execute_query
    rows = execute_query("""
        SELECT * FROM state.encounters WHERE campaign_id = %s ORDER BY created_at DESC
    """, (campaign_id,))
    return jsonify([_serialize(r) for r in rows])


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
            session_id=uuid.UUID(data.get("session_id", "66666666-6666-6666-6666-666666666661")),
            encounter_id=uuid.UUID(data["encounter_id"]) if data.get("encounter_id") else None,
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
            session_id=uuid.UUID(data.get("session_id", "66666666-6666-6666-6666-666666666661")),
            speaker_entity_id=uuid.UUID(data["speaker_entity_id"]),
            speaker_principal_id=uuid.UUID(data["speaker_principal_id"]),
            message=data["message"],
            target_entity_id=uuid.UUID(data["target_entity_id"]) if data.get("target_entity_id") else None,
        )

        from services.ledger.writer import LedgerWriter
        ledger = LedgerWriter()
        results = []
        for event in events:
            r = ledger.append_event(event)
            results.append(r)
            socketio.emit("game_event", _serialize(event.model_dump()), room=str(data["campaign_id"]))

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
        return Response(md, mimetype="text/markdown",
                        headers={"Content-Disposition": f"attachment; filename=session_{session_id}.md"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
            session_id=uuid.UUID(data.get("session_id", "66666666-6666-6666-6666-666666666661")),
            encounter_id=uuid.UUID(data["encounter_id"]) if data.get("encounter_id") else None,
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
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
