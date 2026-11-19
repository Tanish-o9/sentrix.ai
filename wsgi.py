"""Root WSGI entrypoint for Vercel deployment."""
import os
from sentrix_backend.wsgi import application, app

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sentrix_backend.settings")
