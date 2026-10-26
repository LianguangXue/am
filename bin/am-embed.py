#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""am-embed — optional semantic index behind ``am recall --smart``.

This file is the only part of the memory system that needs third-party
packages. It runs under a dedicated interpreter (``$AM_EMBED_PYTHON``, or
``~/.am-embed/venv/bin/python``) so that ``am`` itself stays stdlib-only and
keeps working when this layer is missing or broken.

Modes
-----
``index --idx DIR --chunks FILE``
    Read ``chunks.jsonl``, encode every ``text``, write ``vectors.npy``
    (float32, L2-normalised) and ``meta.json`` side by side.

``query --idx DIR --text "..." --limit N``
    Encode the query and print the top-N chunks as a JSON array on stdout.

``info``
    Report the model and whether the dependencies import.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_MODEL = os.environ.get("AM_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
# BGE's Chinese retrieval instruction. Applied to queries only, never passages.
QUERY_PREFIX = os.environ.get("AM_EMBED_QUERY_PREFIX", "为这个句子生成表示以用于检索相关文章：")

# Keep the model cache inside our own home rather than the shared HuggingFace
# cache: this layer is disposable and must not leave state anywhere else.
os.environ.setdefault("HF_HOME", str(Path.home() / ".am-embed" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def fail(message: str, code: int = 2) -> "None":  # noqa: D401
  """Print to stderr and exit."""
  print(f"am-embed: {message}", file=sys.stderr)
  raise SystemExit(code)


def load_model(name: str):
  """Import sentence-transformers lazily and load the encoder."""
  try:
    from sentence_transformers import SentenceTransformer
  except ImportError:
    fail("sentence-transformers is not installed in this interpreter "
         f"({sys.executable}).\n"
         "  python3 -m venv --system-site-packages ~/.am-embed/venv\n"
         "  ~/.am-embed/venv/bin/pip install sentence-transformers")
  import torch

  threads = int(os.environ.get("AM_EMBED_THREADS", "0") or 0)
  if threads:
    torch.set_num_threads(threads)
  return SentenceTransformer(name, device="cpu")


def read_chunks(path: Path) -> list[dict]:
  """Load the chunk file written by ``am embed``."""
  if not path.is_file():
    fail(f"no chunk file at {path}; run `am embed` first")
  rows = []
  with path.open(encoding="utf-8") as handle:
    for line in handle:
      line = line.strip()
      if not line:
        continue
      try:
        rows.append(json.loads(line))
      except json.JSONDecodeError:
        continue
  return rows


def mode_index(args: argparse.Namespace) -> int:
  """Encode every chunk and persist the normalised matrix."""
  import numpy as np

  idx = Path(args.idx).expanduser()
  idx.mkdir(parents=True, exist_ok=True)
  rows = read_chunks(Path(args.chunks).expanduser())
  if not rows:
    fail("chunk file is empty; nothing to index")

  model = load_model(args.model)
  texts = [str(row.get("text", "")) for row in rows]
  print(f"encoding {len(texts)} chunks with {args.model} on cpu ...", file=sys.stderr)
  vectors = model.encode(
    texts,
    batch_size=args.batch,
    normalize_embeddings=True,
    show_progress_bar=sys.stderr.isatty(),
    convert_to_numpy=True,
  ).astype(np.float32)

  np.save(idx / "vectors.npy", vectors)
  meta = {
    "model": args.model,
    "dim": int(vectors.shape[1]),
    "count": int(vectors.shape[0]),
    "built": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
    "chunks": str(Path(args.chunks).expanduser()),
  }
  (idx / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
  print(f"wrote {vectors.shape[0]}×{vectors.shape[1]} to {idx}", file=sys.stderr)
  return 0


def mode_query(args: argparse.Namespace) -> int:
  """Return the top-N chunks for a query as JSON."""
  import numpy as np

  idx = Path(args.idx).expanduser()
  meta_path = idx / "meta.json"
  if not meta_path.is_file():
    fail(f"no index at {idx}; run `am embed` first")
  meta = json.loads(meta_path.read_text(encoding="utf-8"))
  rows = read_chunks(Path(meta["chunks"]))
  vectors = np.load(idx / "vectors.npy", mmap_mode="r")
  if vectors.shape[0] != len(rows):
    fail(f"index/out of sync: {vectors.shape[0]} vectors vs {len(rows)} chunks; re-run `am embed`")

  model = load_model(meta.get("model") or args.model)
  query = QUERY_PREFIX + args.text
  encoded = model.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0].astype(np.float32)

  scores = np.asarray(vectors) @ encoded
  limit = max(1, min(args.limit, len(scores)))
  top = np.argpartition(-scores, limit - 1)[:limit]
  top = top[np.argsort(-scores[top])]

  out = []
  for position in top:
    row = dict(rows[int(position)])
    row["score"] = round(float(scores[position]), 4)
    out.append(row)
  print(json.dumps(out, ensure_ascii=False))
  return 0


def mode_info(args: argparse.Namespace) -> int:
  """Report interpreter, model and dependency status."""
  print(json.dumps({
    "python": sys.executable,
    "model": args.model,
    "query_prefix": QUERY_PREFIX,
  }, ensure_ascii=False, indent=2))
  try:
    import sentence_transformers

    print(f"sentence-transformers: {sentence_transformers.__version__}", file=sys.stderr)
  except ImportError:
    print("sentence-transformers: MISSING", file=sys.stderr)
    return 1
  return 0


def build_parser() -> argparse.ArgumentParser:
  """Assemble the argument parser."""
  parser = argparse.ArgumentParser(prog="am-embed", description="semantic index for am recall --smart")
  parser.add_argument("--model", default=DEFAULT_MODEL)
  sub = parser.add_subparsers(dest="mode", required=True)

  p = sub.add_parser("index")
  p.add_argument("--idx", required=True)
  p.add_argument("--chunks", required=True)
  p.add_argument("--batch", type=int, default=64)
  p.set_defaults(func=mode_index)

  p = sub.add_parser("query")
  p.add_argument("--idx", required=True)
  p.add_argument("--text", required=True)
  p.add_argument("--limit", type=int, default=12)
  p.set_defaults(func=mode_query)

  p = sub.add_parser("info")
  p.set_defaults(func=mode_info)
  return parser


def main(argv: list[str] | None = None) -> int:
  """Entry point."""
  args = build_parser().parse_args(argv)
  return args.func(args)


if __name__ == "__main__":
  raise SystemExit(main())
