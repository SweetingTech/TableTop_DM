#!/usr/bin/env python3
import os
import sys
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sql", "seed")


def run_seed():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM state.campaigns")
    count = cur.fetchone()[0]
    if count > 0:
        print("  Seed data already present, skipping.")
        cur.close()
        conn.close()
        return

    seed_files = sorted(f for f in os.listdir(SEED_DIR) if f.endswith(".sql"))

    for filename in seed_files:
        filepath = os.path.join(SEED_DIR, filename)
        print(f"  Seeding: {filename}")
        with open(filepath, "r") as f:
            sql = f.read()
        try:
            cur.execute(sql)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  ERROR seeding {filename}: {e}")
            raise

    cur.close()
    conn.close()
    print("  Seed data applied.")


if __name__ == "__main__":
    run_seed()
