"""
WSGI Entrypoint for Gunicorn production deployment.
Exposes the application callable for systemd / Docker / Gunicorn workers (`wsgi:app`).
The app is built here, not in `app.py`, so importing `app` (for `create_app`, `ASSET_VERSION`) has no side effects.
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
