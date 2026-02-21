import os
import json
from flask import Flask, render_template
import psycopg2
import psycopg2.extras

app = Flask(__name__, template_folder="templates", static_folder="static")

def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])

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

@app.route("/api/health")
def health():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}, 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
