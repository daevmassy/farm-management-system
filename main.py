from app import app, init_pool, init_db
import os

print("Initializing connection pool...")
init_pool()
print("Initializing database...")
init_db()
port = int(os.environ.get('PORT', 5000))
print(f"Starting Flask server on http://0.0.0.0:{port}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=port)
