"""
WSGI Entrypoint for Gunicorn production deployment.
Exposes the application callable for systemd / Docker / Gunicorn workers.
"""
from app import app

if __name__ == "__main__":
    app.run()
