"""Stage an allow-listed Lambda source bundle without environments or user data."""

import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root / "build" / "lambda"
destination.mkdir(parents=True, exist_ok=True)
shutil.copytree(
    root / "chromatic",
    destination / "chromatic",
    dirs_exist_ok=True,
    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
)
for name in ("requirements.txt", "requirements-lock.txt"):
    shutil.copy2(root / name, destination / name)
print(f"Lambda source staged at {destination}")
