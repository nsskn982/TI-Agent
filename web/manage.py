#!/usr/bin/env python
"""Django entry point for the TI Agent website.

    python web/manage.py migrate          # once: creates the local user/session DB
    python web/manage.py invite alice      # invite-only: create a login
    python web/manage.py runserver         # http://127.0.0.1:8000
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so `common`, `quant`, `retrieval` import from the repo

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tiweb.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
