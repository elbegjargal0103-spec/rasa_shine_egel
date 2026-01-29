import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "lab_data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        value REAL,
        created_at TEXT DEFAULT (datetime('now'))
    )
    """)
    conn.commit()
    conn.close()
    print("DB created/ready:", DB_PATH)

if __name__ == "__main__":
    init_db()
