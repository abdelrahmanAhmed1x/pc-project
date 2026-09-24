"""Align an existing Compose volume's role password with local .env."""

from pathlib import Path
import subprocess


env_path = Path(__file__).resolve().parents[1] / ".env"
values = dict(
    line.split("=", 1)
    for line in env_path.read_text().splitlines()
    if line and not line.startswith("#") and "=" in line
)
password = values["POSTGRES_PASSWORD"]
escaped = password.replace("'", "''")
subprocess.run(
    ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "pcparts", "-d", "pcparts"],
    input=f"ALTER ROLE pcparts PASSWORD '{escaped}';\n",
    text=True,
    stdout=subprocess.DEVNULL,
    check=True,
)
print("PostgreSQL password matches .env")
