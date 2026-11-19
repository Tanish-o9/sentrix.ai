#!/usr/bin/env python
import os
import sys

# Ensure DJANGO_SETTINGS_MODULE is set at module level for Vercel scanners and scripts
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sentrix_backend.settings")

def main():
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("Couldn't import Django. Is it installed?") from exc
    execute_from_command_line(sys.argv)

if __name__ == "__main__":
    main()

