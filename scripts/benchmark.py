"""Repeatable algorithm benchmark. Generated images, no network or user data."""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np

from chromatic.engine import Method, Options, transfer

parser = argparse.ArgumentParser()
parser.add_argument("--size", type=int, default=256)
parser.add_argument("--repeats", type=int, default=5)
args = parser.parse_args()
if not 1 <= args.size <= 512 or args.repeats < 1:
    parser.error("size must be 1..512 and repeats must be positive")
rng = np.random.default_rng(42)
source = rng.integers(40, 150, (args.size, args.size, 3), dtype=np.uint8)
reference = rng.integers(100, 220, (args.size, args.size, 3), dtype=np.uint8)
rows = []
for method in Method:
    options = Options(method=method)
    transfer(source, reference, options)
    samples = []
    for _ in range(args.repeats):
        started = time.perf_counter()
        output = transfer(source, reference, options)
        samples.append((time.perf_counter() - started) * 1000)
    rows.append(
        {
            "method": method,
            "median_ms": round(statistics.median(samples), 2),
            "min_ms": round(min(samples), 2),
            "max_ms": round(max(samples), 2),
            "palette_mean_error": round(
                float(np.linalg.norm(output.mean((0, 1)) - reference.mean((0, 1)))), 3
            ),
        }
    )
print(json.dumps({"size": args.size, "repeats": args.repeats, "results": rows}, indent=2))
