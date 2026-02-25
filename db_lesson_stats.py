import sqlite3
db = sqlite3.connect("production.db")
cur = db.cursor()

rows = cur.execute("""
SELECT grade, subject, COUNT(*) 
FROM lessons
GROUP BY grade, subject
ORDER BY grade, subject
""").fetchall()

print("LESSONS COUNTS:")
for r in rows:
    print(r)
