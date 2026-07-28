from app import app, init_pool, init_db

print("Initializing connection pool...")
init_pool()
print("Initializing database...")
init_db()
print("Starting Flask server on http://0.0.0.0:5000")
app.run(host='0.0.0.0', port=5000, debug=True)
