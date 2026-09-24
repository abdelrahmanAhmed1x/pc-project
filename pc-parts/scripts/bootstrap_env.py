"""Create local, untracked PostgreSQL credentials once."""

from pathlib import Path
import secrets


root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    print("Using existing .env")
else:
    password = secrets.token_urlsafe(32)
    template = (root / ".env.example").read_text()
    content = template.replace("change-me", password)
    with target.open("x", encoding="utf-8") as env_file:
        env_file.write(content)
    target.chmod(0o600)
    print("Created .env with a generated PostgreSQL password")
