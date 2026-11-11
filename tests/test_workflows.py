"""GitHub Actions files must load: a broken one silently stops the daily ingest ("No jobs were run")."""
import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parent.parent / ".github" / "workflows").glob("*.yml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_valid(path):
    src = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(src)
    assert doc.get("jobs"), "no jobs defined"
    assert doc.get("permissions") == {"contents": "read"}, "keep the job token read-only"
    # GitHub evaluates ${{ ... }} everywhere in the file, comments included; an empty or
    # unclosed expression invalidates the whole workflow.
    assert src.count("${{") == src.count("}}"), "unbalanced expression braces"
    empty = [e for e in re.findall(r"\$\{\{(.*?)\}\}", src, re.S) if not e.strip()]
    assert not empty, "empty ${{ }} expression"
