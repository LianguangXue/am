#!/usr/bin/env python3
"""Focused regression tests for `am` hardening, locking, redaction, and HTTP auth."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
import fcntl
import http.client
from importlib.machinery import SourceFileLoader
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
AM_BIN = REPO_ROOT / "bin" / "am"
sys.path.insert(0, str(REPO_ROOT / "bin"))
import am_work  # noqa: E402


def load_am_module():
  """Load ``bin/am`` as an importable Python module for unit tests."""
  loader = SourceFileLoader("am_cli_hardening", str(AM_BIN))
  spec = importlib.util.spec_from_loader("am_cli_hardening", loader)
  assert spec is not None
  module = importlib.util.module_from_spec(spec)
  loader.exec_module(module)
  return module


AM = load_am_module()


def _free_port() -> int:
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    return int(sock.getsockname()[1])


class HardeningTests(unittest.TestCase):
  """Regression suite for store integrity, CLI behavior, and HTTP safety."""

  def _init_store(self, tmp: Path) -> Path:
    am = tmp / ".agents"
    am.mkdir(parents=True, exist_ok=True)
    cfg = AM.load_config(am)
    AM.save_json(am / "config.json", cfg)
    (am / "tasks").mkdir(exist_ok=True)
    (am / "leases").mkdir(exist_ok=True)
    (am / "journal").mkdir(exist_ok=True)
    (am / "briefs").mkdir(exist_ok=True)
    return am

  def test_detect_agent_ignores_passive_codex_home_and_supports_antigravity(self) -> None:
    """Passive ``CODEX_HOME`` never implies Codex; Antigravity env is detected."""
    base_clean = {k: v for k, v in os.environ.items()
                  if not k.startswith(("CLAUDE", "CODEX", "DSH", "ANTIGRAVITY"))}
    with patch.dict(os.environ, {**base_clean, "CODEX_HOME": "/tmp/codex"}, clear=True):
      self.assertEqual(AM.detect_agent(), "human")
    with patch.dict(os.environ, {**base_clean, "CODEX_HOME": "/tmp/codex",
                                 "ANTIGRAVITY_AGENT": "1"}, clear=True):
      self.assertEqual(AM.detect_agent(), "antigravity")

  def test_store_lock_reentrant_and_thread_safe(self) -> None:
    """``store_lock`` is re-entrant per thread and serializes concurrent writers."""
    with tempfile.TemporaryDirectory() as td:
      am = self._init_store(Path(td))
      with AM.store_lock(am):
        with AM.store_lock(am):
          counter = am / "counter.txt"
          counter.write_text("0", encoding="utf-8")

      errors: list[BaseException] = []

      def bump() -> None:
        try:
          for _ in range(15):
            with AM.store_lock(am):
              val = int(counter.read_text(encoding="utf-8"))
              time.sleep(0.001)
              AM.atomic_write_text(counter, str(val + 1))
        except BaseException as exc:  # pragma: no cover - surfaced below
          errors.append(exc)

      threads = [threading.Thread(target=bump) for _ in range(4)]
      for th in threads:
        th.start()
      for th in threads:
        th.join(timeout=10)
      self.assertFalse(errors)
      self.assertEqual(int(counter.read_text(encoding="utf-8")), 60)

  def test_load_json_strict_and_non_strict_corrupt_handling(self) -> None:
    """Corrupt JSON warns and returns a deep copy unless ``strict=True``."""
    with tempfile.TemporaryDirectory() as td:
      bad = Path(td) / "bad.json"
      bad.write_text("{corrupt", encoding="utf-8")
      default = {"nested": []}
      stderr = io.StringIO()
      with contextlib.redirect_stderr(stderr):
        out = AM.load_json(bad, default, strict=False)
      self.assertEqual(out, {"nested": []})
      self.assertIn("ignoring unreadable JSON", stderr.getvalue())
      out["nested"].append("mutated")
      self.assertEqual(default["nested"], [])
      with self.assertRaises(json.JSONDecodeError):
        AM.load_json(bad, default, strict=True)

  def test_scrub_secrets_redacts_secrets_but_preserves_token_budget(self) -> None:
    """Secrets are masked while benign ``token_budget=...`` labels stay readable."""
    sample = (
      'token_budget=5000 password="secret_pw" api_secret=topsecret123 '
      'Authorization: Bearer abc.def.ghi key=sk-1234567890abcdef '
      'https://alice:hunter2@example.com/repo'
    )
    scrubbed = AM.scrub_secrets(sample)
    self.assertIn("token_budget=5000", scrubbed)
    self.assertNotIn("secret_pw", scrubbed)
    self.assertNotIn("topsecret123", scrubbed)
    self.assertNotIn("abc.def.ghi", scrubbed)
    self.assertNotIn("sk-1234567890abcdef", scrubbed)
    self.assertNotIn("hunter2", scrubbed)

  def test_short_session_codex_consistency_and_state_payload_session_short(self) -> None:
    """Codex ``rollout-...-<uuid>`` normalizes identically across views and tasks."""
    uuid_tail = "019a1111-2222-7333-8444-555566667777"
    rollout = f"rollout-2026-11-14T10-00-00-{uuid_tail}"
    self.assertEqual(AM.short_session("codex", rollout), AM.short_session("codex", uuid_tail))

    with tempfile.TemporaryDirectory() as td:
      am = self._init_store(Path(td))
      AM.save_json(am / "tasks" / "t1.json", {
        "id": "t1", "title": "password=leak_me", "status": "claimed",
        "owner": "codex", "accept": "done", "next": "", "evidence": "",
      })
      AM.save_json(am / "leases" / "t1.json", {
        "task": "t1", "agent": "codex", "session": rollout,
        "expires": (AM.now() + timedelta(minutes=30)).isoformat(),
      })
      with patch.object(AM, "recent_sessions", return_value=[]):
        AM.DASHBOARD_CACHE["payload"] = None
        AM.DASHBOARD_CACHE["at"] = 0.0
        AM.DASHBOARD_CACHE["scanned"] = AM.time.time()
        payload = AM.state_payload(am, AM.load_config(am), ttl=0.0)
      self.assertEqual(len(payload["tasks"]), 1)
      task = payload["tasks"][0]
      self.assertEqual(task["session_short"], AM.short_session("codex", rollout))
      self.assertNotIn("leak_me", task["title"])

  def test_cancel_and_prune_archive_cancelled_task_and_clean_integrations(self) -> None:
    """Cancelled tasks archive with their leases and delegate handoff folders cleaned."""
    with tempfile.TemporaryDirectory() as td:
      am = self._init_store(Path(td))
      cfg = AM.load_config(am)
      args = AM.build_parser().parse_args(["--root", str(am), "task", "add", "demo",
                                           "--title", "demo task", "--accept", "tests pass"])
      args.agent = "codex"
      self.assertEqual(AM.cmd_task(am, cfg, args), 0)

      AM.save_json(am / "leases" / "demo.json", {
        "task": "demo", "agent": "codex", "session": "sess-1",
        "expires": (AM.now() + timedelta(minutes=30)).isoformat(),
      })
      integ = am / "integrations" / "delegate" / "demo"
      integ.mkdir(parents=True, exist_ok=True)
      (integ / "index.json").write_text("[]", encoding="utf-8")

      cancel_args = AM.build_parser().parse_args(["--root", str(am), "cancel", "demo", "--reason", "superseded"])
      cancel_args.agent = "codex"
      self.assertEqual(AM.cmd_cancel(am, cfg, cancel_args), 0)
      rec = AM.load_json(am / "tasks" / "demo.json", {})
      self.assertEqual(rec["status"], "cancelled")
      self.assertEqual(rec["cancelled_reason"], "superseded")
      self.assertFalse((am / "leases" / "demo.json").exists())

      # Backdate so prune retention picks up the cancelled task, and restore a lease/integ fixture to verify cleanup.
      rec["updated"] = (AM.now() - timedelta(days=120)).isoformat()
      AM.save_json(am / "tasks" / "demo.json", rec)
      AM.save_json(am / "leases" / "demo.json", {"task": "demo", "agent": "codex"})
      prune_args = AM.build_parser().parse_args(["--root", str(am), "prune", "--days", "30", "--yes"])
      self.assertEqual(AM.cmd_prune(am, cfg, prune_args), 0)
      self.assertFalse((am / "tasks" / "demo.json").exists())
      self.assertFalse((am / "leases" / "demo.json").exists())
      self.assertFalse(integ.exists())
      archived = list((am / "archive" / "tasks").glob("tasks-*.jsonl.gz"))
      self.assertTrue(archived)

  def test_doctor_flags_corrupt_json_and_warns_missing_accept(self) -> None:
    """``cmd_doctor`` returns 1 on corrupt store JSON and warns when ``accept`` is absent."""
    with tempfile.TemporaryDirectory() as td:
      am = self._init_store(Path(td))
      cfg = AM.load_config(am)
      (Path(td) / "AGENTS.md").write_text("am:entry\n", encoding="utf-8")
      (Path(td) / "CLAUDE.md").write_text("am:entry\n", encoding="utf-8")
      AM.append_event(am, {"ts": AM.iso(AM.now()), "agent": "codex", "type": "goal", "summary": "Ship cleanly"})
      AM.save_json(am / "tasks" / "adopted.json", {
        "id": "adopted", "title": "Adopted work", "status": "open", "owner": None, "accept": "",
      })

      doc_args = AM.build_parser().parse_args(["--root", str(am), "doctor"])
      out = io.StringIO()
      with contextlib.redirect_stdout(out):
        rc = AM.cmd_doctor(am, cfg, doc_args)
      self.assertEqual(rc, 0)
      self.assertIn("no acceptance criterion", out.getvalue())

      (am / "hidden.json").write_text("{broken", encoding="utf-8")
      out = io.StringIO()
      with contextlib.redirect_stdout(out):
        rc_bad = AM.cmd_doctor(am, cfg, doc_args)
      self.assertEqual(rc_bad, 1)
      self.assertIn("corrupt JSON", out.getvalue())

  def test_serve_http_token_origin_and_payload_hardening(self) -> None:
    """``am serve --token`` enforces auth, origin check, Content-Type, and size cap."""
    with tempfile.TemporaryDirectory() as td:
      am = self._init_store(Path(td))
      port = _free_port()
      token = "top-secret-token-xyz"
      proc = subprocess.Popen(
        [sys.executable, "-B", str(AM_BIN), "--root", str(am),
         "serve", "--host", "127.0.0.1", "--port", str(port), "--token", token],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
      )
      try:
        deadline = time.monotonic() + 8.0
        ready = False
        while time.monotonic() < deadline:
          try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
            conn.request("GET", "/")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            self.assertEqual(resp.status, 401)
            ready = True
            break
          except OSError:
            time.sleep(0.05)
        self.assertTrue(ready, "am serve failed to start")

        for headers, path in (
          ({"X-AM-Token": token}, "/api/delegate"),
          ({"Authorization": f"Bearer {token}"}, "/api/delegate"),
          ({}, f"/api/delegate?token={token}"),
        ):
          conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
          conn.request("GET", path, headers=headers)
          resp = conn.getresponse()
          resp.read()
          conn.close()
          self.assertEqual(resp.status, 200)

        # Mismatched Origin -> 403
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
        conn.request("POST", "/api/hide", body=b'{"short":"abc"}', headers={
          "X-AM-Token": token, "Origin": "https://evil.invalid", "Content-Type": "application/json",
        })
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 403)

        # Non-JSON Content-Type -> 415
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
        conn.request("POST", "/api/hide", body=b'short=abc', headers={
          "X-AM-Token": token, "Content-Type": "text/plain",
        })
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 415)

        # Oversized Content-Length -> 413
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
        conn.request("POST", "/api/hide", body=b"x", headers={
          "X-AM-Token": token, "Content-Type": "application/json", "Content-Length": "70000",
        })
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 413)
      finally:
        proc.terminate()
        try:
          proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
          proc.kill()
          proc.wait(timeout=3)
        if proc.stderr is not None:
          proc.stderr.close()

  def test_am_work_symlink_rules_and_shared_read_locks(self) -> None:
    """``am_work`` allows symlinked ancestor dirs, blocks leaf symlinks, and uses LOCK_SH for reads."""
    with tempfile.TemporaryDirectory() as td:
      root = Path(td)
      real_parent = root / "real_parent"
      real_parent.mkdir()
      link_parent = root / "link_parent"
      link_parent.symlink_to(real_parent)
      target = real_parent / "artifact.txt"
      target.write_text("evidence\n", encoding="utf-8")

      digests = am_work.fingerprints([str(link_parent / "artifact.txt")])
      self.assertEqual(len(digests), 1)

      leaf_link = real_parent / "leaf_link.txt"
      leaf_link.symlink_to(target)
      with self.assertRaises(ValueError):
        am_work.fingerprints([str(leaf_link)])

      am = self._init_store(root)
      work_dir = am / "work"
      work_dir.mkdir(mode=0o700, exist_ok=True)
      am_work.save(work_dir / "index.json", {"artifacts": [], "requests": [], "watches": []})
      lock_file = (work_dir / "state.lock").open("a+", encoding="utf-8")
      try:
        # Hold LOCK_SH on a separate descriptor; read-only `search` also uses LOCK_SH and must not block.
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        res = am_work.execute(am, "search", {"project": "proj", "query": "x"})
        self.assertEqual(res["artifacts"], [])
      finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
  unittest.main()
