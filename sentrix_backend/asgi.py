"""ASGI config for SENTRIX.ai project."""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sentrix_backend.settings")

application = get_asgi_application()
app = application
