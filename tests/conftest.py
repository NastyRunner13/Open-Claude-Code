"""Isolate user-level provider profiles from the developer's ~/.occ."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_user_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("OCC_PROFILES_PATH", str(tmp_path / ".occ-test-home" / "profiles.yml"))
    monkeypatch.setenv("OCC_CACHE_DIR", str(tmp_path / ".occ-test-home" / "cache"))
    monkeypatch.delenv("OCC_PROFILE", raising=False)
