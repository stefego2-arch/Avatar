import sqlite3

c = sqlite3.connect("production.db")
cur = c.cursor()
rows = cur.execute("""
select grade, subject, count(*) 
from lessons
group by grade, subject
order by grade, subject
""").fetchall()

print(rows)
