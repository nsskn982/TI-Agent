"""Invite-only accounts: `python web/manage.py invite alice [--email a@b.c] [--admin]`.

Prints a one-time random password; the user should change it in /admin/password_change/
(staff) or you reset it here again.
"""
import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create (or reset) a login for an invited user and print a random password."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--email", default="")
        parser.add_argument("--admin", action="store_true", help="Also grant access to /admin/")

    def handle(self, username, email, admin, **_):
        if not username.strip():
            raise CommandError("username is required")
        User = get_user_model()
        user, created = User.objects.get_or_create(username=username, defaults={"email": email})
        password = secrets.token_urlsafe(12)
        user.set_password(password)
        if email:
            user.email = email
        user.is_staff = user.is_superuser = bool(admin)
        user.save()
        verb = "Created" if created else "Reset password for"
        self.stdout.write(self.style.SUCCESS(f"{verb} {username}. Password (shown once): {password}"))
