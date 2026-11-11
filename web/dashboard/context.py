"""Template context shared by every page."""
from django.conf import settings

from dashboard.repo import safe_url


def contact(request):
    """Contact links (LinkedIn, GitHub) for the header tab and the closing scene.

    Only http(s) URLs are shown; an unset or unsafe URL simply hides that icon."""
    links = []
    for key, label in (("linkedin", "LinkedIn"), ("github", "GitHub")):
        url = safe_url(getattr(settings, f"CONTACT_{key.upper()}_URL", "") or None)
        if url:
            links.append({"key": key, "label": label, "url": url})
    return {"contact_links": links}
