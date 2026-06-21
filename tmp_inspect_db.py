import sqlite3

conn = sqlite3.connect('Paydaytest.db')
cur = conn.cursor()

print('=== pay_structure columns ===')
try:
    cur.execute('PRAGMA table_info(pay_structure)')
    cols = cur.fetchall()
    for c in cols:
        print(c)
except Exception as e:
    print('PRAGMA error:', e)

print('\n=== sample rows ===')
try:
    cur.execute('SELECT id, empid, pay_term, active FROM pay_structure LIMIT 5')
    for row in cur.fetchall():
        print(row)
except Exception as e:
    print('select error:', e)

conn.close()
