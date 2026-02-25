import sqlite3

db = sqlite3.connect("production.db")
cur = db.cursor()

print("TABLES:")
for (name,) in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    print(" -", name)

def info(table):
    print(f"\nPRAGMA table_info({table}):")
    try:
        rows = cur.execute(f"PRAGMA table_info({table})").fetchall()
        print(rows if rows else "(no rows / table missing)")
    except Exception as e:
        print("ERROR:", e)

# încearcă tabele uzuale
for t in ["users", "lessons", "lesson_progress", "sessions", "exercises", "results"]:
    info(t)
print("\nPRAGMA table_info(progress):")
print(cur.execute("PRAGMA table_info(progress)").fetchall())

print("\nSample progress rows:")
try:
    print(cur.execute("SELECT * FROM progress LIMIT 5").fetchall())
except Exception as e:
    print("ERROR:", e)