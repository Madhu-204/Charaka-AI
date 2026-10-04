"""Tests for the opt-in document-scope reaper.

The reaper is the answer to "user_chroma_db grows forever": document
collections are keyed by a client-supplied session scope, so every new browser
session mints another collection and nothing ever removed them. The fix is
deliberately opt-in and silent by default, so the most important thing to test
is that a deployment which never set the TTL deletes nothing at all.
"""

import json

import pytest

from app import documents


class TestReaperIsOffByDefault:
    def test_no_ttl_env_means_no_deletion(self, monkeypatch):
        monkeypatch.delenv("CHARAKA_DOC_TTL_DAYS", raising=False)
        assert documents._ttl_days() is None

    def test_reaper_is_a_noop_without_a_ttl(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CHARAKA_DOC_TTL_DAYS", raising=False)
        monkeypatch.setattr(documents, "SCOPES_FILE", tmp_path / "scopes.json")
        monkeypatch.setattr(documents, "_get_client", lambda: _FakeClient())
        # Even given a scope that looks ancient, an unset TTL must not delete it.
        monkeypatch.setattr(
            documents, "_load_scopes",
            lambda: {"user_doc_a": "2001-01-01T00:00:00+00:00"},
        )
        assert documents.reap_expired() == []

    @pytest.mark.parametrize("raw", ["", "0", "-5", "abc", " "])
    def test_nonsense_ttl_values_disable_rather_than_crash(
        self, monkeypatch, raw
    ):
        monkeypatch.setenv("CHARAKA_DOC_TTL_DAYS", raw)
        assert documents._ttl_days() is None

    def test_positive_ttl_enables(self, monkeypatch):
        monkeypatch.setenv("CHARAKA_DOC_TTL_DAYS", "30")
        assert documents._ttl_days() == 30


class TestReapExpired:
    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch, tmp_path):
        self.scopes = tmp_path / "scopes.json"
        monkeypatch.setattr(documents, "SCOPES_FILE", self.scopes)
        self.client = _FakeClient()
        monkeypatch.setattr(documents, "_get_client", lambda: self.client)
        self.write = lambda d: self.scopes.write_text(
            json.dumps(d), encoding="utf-8"
        )
        self.read = lambda: json.loads(self.scopes.read_text(encoding="utf-8"))

    def test_idle_scope_is_deleted(self):
        self.client.collections["user_doc_old"] = _FakeCollection()
        self.write({"user_doc_old": "2001-01-01T00:00:00+00:00"})
        assert documents.reap_expired(ttl_days=30) == ["user_doc_old"]
        assert "user_doc_old" not in self.client.collections
        assert self.read() == {}

    def test_recently_used_scope_survives(self):
        self.client.collections["user_doc_new"] = _FakeCollection()
        self.write({"user_doc_new": documents._now().isoformat(timespec="seconds")})
        assert documents.reap_expired(ttl_days=30) == []
        assert "user_doc_new" in self.client.collections

    def test_explicit_ttl_overrides_the_env(self, monkeypatch):
        monkeypatch.setenv("CHARAKA_DOC_TTL_DAYS", "0")  # disabled in env
        self.client.collections["user_doc_old"] = _FakeCollection()
        self.write({"user_doc_old": "2001-01-01T00:00:00+00:00"})
        # ...but an explicit argument still works, so a manual cron can reap
        # without mutating the process environment.
        assert documents.reap_expired(ttl_days=1) == ["user_doc_old"]

    def test_stale_entry_for_a_missing_collection_is_forgotten(self):
        # The collection was deleted out of band; the tracker must not keep
        # retrying it forever.
        self.write({"user_doc_gone": "2001-01-01T00:00:00+00:00"})
        assert documents.reap_expired(ttl_days=30) == []
        assert self.read() == {}

    def test_corrupt_timestamp_is_treated_as_expired(self):
        self.client.collections["user_doc_weird"] = _FakeCollection()
        self.write({"user_doc_weird": "not-a-date"})
        assert documents.reap_expired(ttl_days=30) == ["user_doc_weird"]

    def test_untracked_collection_is_left_alone(self):
        """The reaper only reaps what it has evidence about.

        A collection with no tracker entry has no known activity, but it also has
        no known age, so silently deleting it on the first pass would be a
        surprise. Backfill instead: run with tracking on, or delete via the API.
        """
        self.client.collections["user_doc_legacy"] = _FakeCollection()
        assert documents.reap_expired(ttl_days=1) == []
        assert "user_doc_legacy" in self.client.collections

    def test_reaper_tolerates_a_broken_client(self, monkeypatch):
        monkeypatch.setattr(
            documents, "_get_client", lambda: _ExplodingClient()
        )
        # A failure to enumerate collections must not raise into startup.
        assert documents.reap_expired(ttl_days=1) == []


class TestScopeTracking:
    def test_touch_is_a_noop_while_disabled(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CHARAKA_DOC_TTL_DAYS", raising=False)
        target = tmp_path / "scopes.json"
        monkeypatch.setattr(documents, "SCOPES_FILE", target)
        documents._touch("user_doc_a")
        assert not target.exists()

    def test_touch_records_the_scope_when_enabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CHARAKA_DOC_TTL_DAYS", "30")
        target = tmp_path / "scopes.json"
        monkeypatch.setattr(documents, "SCOPES_FILE", target)
        documents._touch("user_doc_a")
        assert "user_doc_a" in json.loads(target.read_text(encoding="utf-8"))

    def test_corrupt_sidecar_is_treated_as_empty(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CHARAKA_DOC_TTL_DAYS", "30")
        target = tmp_path / "scopes.json"
        target.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(documents, "SCOPES_FILE", target)
        assert documents._load_scopes() == {}
        # And tracking recovers rather than raising on every upload.
        documents._touch("user_doc_a")
        assert "user_doc_a" in json.loads(target.read_text(encoding="utf-8"))


class _FakeCollection:
    name = "user_doc_fake"


class _FakeClient:
    def __init__(self):
        self.collections = {}
        self.deleted = []

    def list_collections(self):
        return [type("C", (), {"name": n})() for n in self.collections]

    def delete_collection(self, name):
        if name not in self.collections:
            raise ValueError(f"no such collection: {name}")
        self.deleted.append(name)
        del self.collections[name]


class _ExplodingClient:
    def list_collections(self):
        raise RuntimeError("chroma unavailable")
