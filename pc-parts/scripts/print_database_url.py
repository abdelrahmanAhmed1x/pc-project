"""Read the local connection URL for the database test command."""

from pathlib import Path


env_path = Path(__file__).resolve().parents[1] / ".env"
for line in env_path.read_text().splitlines():
    if line.startswith("DATABASE_URL="):
        print(line.split("=", 1)[1])
        break
else:
    raise SystemExit("DATABASE_URL is missing from .env")
