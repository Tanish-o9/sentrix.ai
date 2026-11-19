"""WSGI config for SENTRIX.ai project."""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sentrix_backend.settings")

application = get_wsgi_application()
app = application
