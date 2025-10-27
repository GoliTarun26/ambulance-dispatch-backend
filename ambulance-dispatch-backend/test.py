from app import pool

conn = pool.get_connection()
cursor = conn.cursor(dictionary=True)
cursor.execute("SELECT * FROM ambulances")
print(cursor.fetchall())
cursor.close()
conn.close()
