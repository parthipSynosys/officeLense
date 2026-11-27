#!/usr/bin/env python3
"""Benchmark the /api/match search query at realistic scale.

Creates a throw-away schema `eventlens_bench` in the configured database, fills
it with N random L2-normalised 128-d vectors spread over E events (like real
SFace embeddings), builds the same indexes as production, and times the exact
query used by app/services/matching.py with and without event filters.

    python scripts/benchmark_match.py                   # 100k faces, 50 events
    python scripts/benchmark_match.py --faces 200000 --events 100 --runs 20

The schema is dropped at the end (use --keep to keep it for experiments).
Nothing in the application tables is touched.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
import uuid
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402

SCHEMA = "eventlens_bench"


def dsn() -> str:
    return get_settings().DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")


def random_unit(n: int, rng: np.random.Generator) -> np.ndarray:
    v = rng.standard_normal((n, 128)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


QUERY = f"""
SELECT f.photo_id, MIN(LEAST({{dists}})) AS d
FROM {SCHEMA}.faces f
JOIN {SCHEMA}.events e ON e.id = f.event_id
WHERE e.is_published {{filters}}
  AND LEAST({{dists}}) <= %(maxd)s
GROUP BY f.photo_id
"""


def build_query(n_selfies: int, filtered: bool) -> str:
    dists = ", ".join(f"f.embedding <=> %(q{i})s" for i in range(n_selfies))
    filters = "AND f.event_id = ANY(%(events)s)" if filtered else ""
    return QUERY.format(dists=dists, filters=filters)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--faces", type=int, default=100_000)
    ap.add_argument("--events", type=int, default=50)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    rng = np.random.default_rng(42)
    with psycopg.connect(dsn(), autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {SCHEMA}")
        conn.execute(f"CREATE TABLE {SCHEMA}.events (id uuid PRIMARY KEY, is_published bool NOT NULL)")
        conn.execute(
            f"CREATE TABLE {SCHEMA}.faces (id bigserial PRIMARY KEY, photo_id uuid NOT NULL, "
            f"event_id uuid NOT NULL, embedding vector(128) NOT NULL)"
        )
        event_ids = [uuid.uuid4() for _ in range(args.events)]
        with conn.cursor().copy(f"COPY {SCHEMA}.events (id, is_published) FROM STDIN") as cp:
            for e in event_ids:
                cp.write_row((e, True))

        print(f"Inserting {args.faces} faces...", flush=True)
        t0 = time.perf_counter()
        vectors = random_unit(args.faces, rng)
        with conn.cursor().copy(
            f"COPY {SCHEMA}.faces (photo_id, event_id, embedding) FROM STDIN WITH (FORMAT BINARY)"
        ) as cp:
            cp.set_types(["uuid", "uuid", "vector"])
            photo = uuid.uuid4()
            for i, v in enumerate(vectors):
                if i % 4 == 0:  # ~4 faces per photo
                    photo = uuid.uuid4()
                cp.write_row((photo, event_ids[i % len(event_ids)], v))
        print(f"  done in {time.perf_counter() - t0:.1f}s")

        print("Building indexes (btree event_id + HNSW cosine)...", flush=True)
        t0 = time.perf_counter()
        conn.execute(f"CREATE INDEX ON {SCHEMA}.faces (event_id)")
        conn.execute(
            f"CREATE INDEX ON {SCHEMA}.faces USING hnsw (embedding vector_cosine_ops) "
            f"WITH (m = 16, ef_construction = 64)"
        )
        conn.execute(f"ANALYZE {SCHEMA}.faces")
        print(f"  done in {time.perf_counter() - t0:.1f}s")

        # Queries: perturbed copies of stored vectors (so there ARE matches).
        def params(n_selfies: int, filtered: bool) -> dict:
            p: dict = {"maxd": 1 - 0.363}
            for i in range(n_selfies):
                base = vectors[rng.integers(0, len(vectors))]
                q = base + rng.standard_normal(128).astype(np.float32) * 0.03
                p[f"q{i}"] = q / np.linalg.norm(q)
            if filtered:
                p["events"] = event_ids[: max(1, len(event_ids) // 5)]
            return p

        print(f"\nTiming ({args.runs} runs each, first run discarded as warm-up):")
        results = []
        for n_selfies in (1, 3):
            for filtered in (False, True):
                sql = build_query(n_selfies, filtered)
                times, hits = [], 0
                for r in range(args.runs + 1):
                    p = params(n_selfies, filtered)
                    t0 = time.perf_counter()
                    rows = conn.execute(sql, p).fetchall()
                    dt = (time.perf_counter() - t0) * 1000
                    if r > 0:
                        times.append(dt)
                        hits = len(rows)
                label = f"{n_selfies} selfie(s), {'filtered (20% of events)' if filtered else 'all events'}"
                results.append((label, statistics.median(times), max(times), hits))

        plan = conn.execute("EXPLAIN " + build_query(1, True), params(1, True)).fetchall()

        for label, med, worst, hits in results:
            print(f"  {label:42s} median {med:7.1f} ms   max {worst:7.1f} ms   ({hits} photos)")
        print("\nQuery plan (1 selfie, filtered) - no HNSW index scan means the search is exact:")
        for (line,) in plan:
            print("  " + (line if len(line) <= 160 else line[:157] + "..."))

        if not args.keep:
            conn.execute(f"DROP SCHEMA {SCHEMA} CASCADE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
