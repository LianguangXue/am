"""Quota-first local artifact exchange, bounded mail and receipt observers (no LLM)."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from typing import Any

_READ_ONLY_ACTIONS = frozenset({"search", "get", "inbox", "stage-check"})


def key(value: object) -> str:
  """Validate and return a safe single-segment identifier.

  Args:
    value: Candidate identifier value.

  Returns:
    Validated identifier string.

  Raises:
    ValueError: If ``value`` is not a safe 1..100-character identifier.
  """
  if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
    raise ValueError("Invalid identifier")
  return value


def read(path: Path, default: bytes | None = None) -> bytes | None:
  """Read a regular, non-symlink file up to 16 MiB without blocking on FIFOs.

  Args:
    path: Target file path.
    default: Value returned when ``path`` does not exist.

  Returns:
    Raw file bytes, or ``default`` if absent.

  Raises:
    ValueError: If ``path`` is not a regular file or exceeds 16 MiB.
  """
  try:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
      if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        raise ValueError("Expected regular file")
      raw = stream.read(16 * 1024 * 1024 + 1)
      if len(raw) > 16 * 1024 * 1024:
        raise ValueError("File exceeds 16 MiB; reference a producer manifest instead")
    return raw
  except FileNotFoundError:
    return default


def load(path: Path, default: Any = None) -> Any:
  """Load a JSON file safely, returning ``default`` when absent.

  Args:
    path: JSON file path to load.
    default: Value returned when ``path`` does not exist.

  Returns:
    Decoded JSON value or ``default``.
  """
  raw = read(path)
  return json.loads(raw) if raw is not None else default


def save(path: Path, value: Any) -> None:
  """Atomically persist JSON with flush and fsync.

  Args:
    path: Destination JSON file path.
    value: JSON-serializable object.
  """
  fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".work-")
  try:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
      json.dump(value, stream, ensure_ascii=False)
      stream.flush()
      os.fsync(stream.fileno())
    os.replace(tmp, path)
  finally:
    if os.path.exists(tmp):
      os.unlink(tmp)


def fingerprints(files: Any) -> dict[str, str]:
  """Compute SHA-256 digests for 1..16 regular, non-symlink evidence files.

  Args:
    files: List of 1..16 file paths.

  Returns:
    Mapping from normalized absolute path string to SHA-256 hex digest.

  Raises:
    ValueError: If the list is invalid, contains symlinks, or misses files.
  """
  if not isinstance(files, list) or not 1 <= len(files) <= 16:
    raise ValueError("Nominate 1..16 evidence files/manifests")
  result: dict[str, str] = {}
  for name in files:
    if not isinstance(name, str) or not name.strip():
      raise ValueError("Invalid evidence path")
    path = Path(os.path.abspath(str(Path(name).expanduser())))
    if path.is_symlink():
      raise ValueError("Symlink evidence not supported")
    raw = read(path)
    if raw is None:
      raise ValueError("Evidence missing")
    result[str(path)] = hashlib.sha256(raw).hexdigest()
  return result


def freshness(card: dict[str, Any]) -> str:
  """Check whether all nominated files still match their recorded digests.

  Args:
    card: Artifact or stage card containing a ``files`` digest mapping.

  Returns:
    ``"unchanged"`` if every digest matches, otherwise ``"stale"``.
  """
  try:
    return "unchanged" if fingerprints(list(card["files"])) == card["files"] else "stale"
  except (OSError, ValueError):
    return "stale"


def stage_valid(root: Path, record: dict[str, Any]) -> bool:
  """Verify a stage record and its transitive dependencies remain unchanged.

  Args:
    root: Work directory under ``.agents``.
    record: Stage record dictionary.

  Returns:
    True when the stage and every dependency remain intact.
  """
  pending = [record]
  seen: set[str] = set()
  while pending:
    item = pending.pop()
    if item["id"] in seen:
      continue
    seen.add(item["id"])
    if len(seen) > 100 or freshness(item) != "unchanged":
      return False
    for dep in item["requires"]:
      child = load(root / ("stage-" + key(dep) + ".json"))
      if not child or child["task_id"] != record["task_id"]:
        return False
      pending.append(child)
  return True


def execute(am: Path, action: str, data: dict[str, Any]) -> dict[str, Any]:
  """Execute one local artifact, mail, watch, or stage protocol action.

  Args:
    am: Path to the ``.agents`` store directory.
    action: Protocol verb.
    data: Validated request object.

  Returns:
    Protocol response dictionary.

  Raises:
    ValueError: On invalid arguments, conflicts, or unknown actions.
  """
  root = am / "work"
  root.mkdir(mode=0o700, exist_ok=True)
  lock_mode = fcntl.LOCK_SH if action in _READ_ONLY_ACTIONS else fcntl.LOCK_EX
  with (root / "state.lock").open("a", encoding="utf-8") as lock:
    fcntl.flock(lock, lock_mode)
    index = load(root / "index.json", {"artifacts": [], "requests": [], "watches": []})
    if action == "publish":
      ident, project = key(data["id"]), key(data["project"])
      key(data["task_id"])
      key(data["session_id"])
      if not (am / "tasks" / (data["task_id"] + ".json")).is_file():
        raise ValueError("Unknown am task")
      if not isinstance(data.get("summary"), str) or not 1 <= len(data["summary"]) <= 2000:
        raise ValueError("Summary must be 1..2000 characters")
      if not isinstance(data.get("evidence"), str) or not 1 <= len(data["evidence"]) <= 2000:
        raise ValueError("Validation evidence is required, at most 2000 characters")
      files = fingerprints(data["files"])
      path = root / ("artifact-" + ident + ".json")
      old = load(path)
      if old and (old["project"] != project or old["task_id"] != data["task_id"] or
                  old["session_id"] != data["session_id"] or data.get("expected_revision") != old["revision"]):
        raise ValueError("Artifact project/revision conflict")
      card = {k: data.get(k) for k in ("id", "project", "task_id", "session_id", "summary", "evidence")}
      card.update(files=files, revision=(old or {}).get("revision", 0) + 1, created_at=time.time())
      if ident not in index["artifacts"]:
        if len(index["artifacts"]) >= 1000:
          raise ValueError("Artifact index limit reached")
        index["artifacts"].append(ident)
      save(path, card)
      save(root / "index.json", index)
      return card
    if action in {"search", "get"}:
      project = key(data["project"])
      query = str(data.get("query", "")).lower()[:1000]
      ids = [key(data["id"])] if action == "get" else index["artifacts"]
      cards = []
      for ident in ids:
        c = load(root / ("artifact-" + ident + ".json"))
        if c and c["project"] == project:
          score = sum(term in (c["summary"] + " " + c["evidence"]).lower() for term in query.split())
          if action == "get" or score:
            cards.append((score, c))
      chosen = sorted(cards, key=lambda pair: (pair[0], pair[1]["created_at"]), reverse=True)[:3]
      return {
        "artifacts": [
          {**c, "freshness": freshness(c)} if action == "get" else
          {k: c[k] for k in ("id", "project", "revision")} | {
            "summary": c["summary"][:500],
            "evidence": c["evidence"][:200],
            "freshness": "unchecked; use get to validate evidence",
          }
          for _, c in chosen
        ],
        "inference_calls": 0,
        "scope": "Only nominated evidence/manifests; unchanged is not a new validation",
      }
    if action == "configure":
      task = key(data["task_id"])
      if not (am / "tasks" / (task + ".json")).is_file():
        raise ValueError("Unknown am task")
      if type(data.get("enabled")) is not bool:
        raise ValueError("Explicit enabled boolean required")
      policy = load(root / ("policy-" + task + ".json"), {"used": 0})
      policy.update(enabled=data["enabled"])
      save(root / ("policy-" + task + ".json"), policy)
      return policy
    if action == "ask":
      task = key(data["task_id"])
      sender = key(data["session_id"])
      target = key(data["target_session"])
      question = data.get("question")
      if sender == target or data.get("parent_request") or not isinstance(question, str) or not 1 <= len(question) <= 2000:
        raise ValueError("One bounded question to one other session; forwarding prohibited")
      signature = json.dumps([task, sender, target, question, data.get("artifact_versions", {})], sort_keys=True)
      ident = hashlib.sha256(signature.encode()).hexdigest()
      path = root / ("request-" + ident + ".json")
      old = load(path)
      if old:
        if ident not in index["requests"]:
          index["requests"].append(ident)
          save(root / "index.json", index)
        return old
      policy = load(root / ("policy-" + task + ".json"), {})
      if not policy.get("enabled") or policy.get("used", 0) >= 1:
        raise ValueError("Question budget disabled or exhausted (one per am task)")
      if len(index["requests"]) >= 1000:
        raise ValueError("Request index limit reached")
      # Reserve budget before publishing. A crash can consume one slot, never overspend it.
      policy["used"] = policy.get("used", 0) + 1
      save(root / ("policy-" + task + ".json"), policy)
      record = {
        "id": ident, "task_id": task, "session_id": sender, "target_session": target,
        "question": question, "status": "queued", "reply": None, "created_at": time.time(),
        "limits": {"reply_chars": 2000, "forwarding": False, "automatic_execution": False},
      }
      save(path, record)
      index["requests"].append(ident)
      save(root / "index.json", index)
      return record
    if action in {"inbox", "reply"}:
      session = key(data["session_id"])
      if action == "inbox":
        rows = [load(root / ("request-" + ident + ".json")) for ident in index["requests"]]
        return {"requests": [r for r in rows if r and (r["target_session"] == session or r["session_id"] == session)][-10:]}
      ident = key(data["id"])
      path = root / ("request-" + ident + ".json")
      r = load(path)
      if not r or r["target_session"] != session:
        raise ValueError("Request belongs to another recipient")
      reply = data.get("reply")
      if not isinstance(reply, str) or not 1 <= len(reply) <= 2000:
        raise ValueError("Reply must be 1..2000 characters")
      if r["status"] == "answered":
        if r["reply"] != reply:
          raise ValueError("Conflicting duplicate reply")
        return r
      r.update(status="answered", reply=reply)
      save(path, r)
      return r
    if action == "watch":
      ident = key(data["id"])
      task = key(data["task_id"])
      session = key(data["session_id"])
      if not (am / "tasks" / (task + ".json")).is_file():
        raise ValueError("Unknown am task")
      manifest = str(Path(data["manifest"]).expanduser().absolute())
      record = {"id": ident, "task_id": task, "session_id": session, "manifest": manifest,
                "status": "waiting", "acknowledged": False}
      path = root / ("watch-" + ident + ".json")
      old = load(path)
      if old:
        if any(old[k] != record[k] for k in ("task_id", "session_id", "manifest")):
          raise ValueError("Watch identity conflict")
        return old
      if len(index["watches"]) >= 1000:
        raise ValueError("Watch index limit reached")
      save(path, record)
      index["watches"].append(ident)
      save(root / "index.json", index)
      return record
    if action in {"poll", "ack"}:
      ident = key(data["id"])
      path = root / ("watch-" + ident + ".json")
      r = load(path)
      if not r or r["session_id"] != data["session_id"]:
        raise ValueError("Watch belongs to another session")
      if action == "ack":
        if r["status"] == "waiting":
          raise ValueError("No completion event to acknowledge")
        if r["acknowledged"]:
          return r
        r["acknowledged"] = True
      elif r["status"] == "waiting":
        try:
          receipt = load(Path(r["manifest"]))
          if receipt and receipt.get("status") in {"completed", "failed"}:
            r.update(status=receipt["status"], event_id="watch-" + ident,
                     evidence=str(receipt.get("evidence", ""))[:2000], finished_at=time.time())
        except (OSError, ValueError, AttributeError):
          return {**r, "receipt_error": True}
        if r["status"] == "waiting":
          return r
      else:
        return r
      save(path, r)
      return r
    if action == "stage":
      ident = key(data["id"])
      task = key(data["task_id"])
      if not (am / "tasks" / (task + ".json")).is_file():
        raise ValueError("Unknown am task")
      deps = data.get("requires", [])
      if not isinstance(deps, list) or len(deps) > 16:
        raise ValueError("Bounded stage dependencies required")
      for dep in deps:
        r = load(root / ("stage-" + key(dep) + ".json"))
        if not r or r["task_id"] != task or not stage_valid(root, r):
          raise ValueError("Dependency missing or changed; do not repeat side effects blindly")
      path = root / ("stage-" + ident + ".json")
      old = load(path)
      if old:
        raise ValueError("Stage already recorded; inspect/revalidate rather than replay")
      record = {
        "id": ident, "task_id": task, "files": fingerprints(data["files"]),
        "evidence": str(data.get("evidence", ""))[:2000], "requires": deps,
      }
      if not record["evidence"]:
        raise ValueError("Evidence required")
      save(path, record)
      return record
    if action == "stage-check":
      r = load(root / ("stage-" + key(data["id"]) + ".json"))
      if not r:
        raise ValueError("Unknown stage")
      return {
        "freshness": "unchanged" if stage_valid(root, r) else "stale",
        "stage": r,
        "scope": "Recorded evidence only; not proof a remote side effect did not occur",
      }
    raise ValueError("Unknown work action")
