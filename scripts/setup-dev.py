"""Creates local development configuration without printing or replacing secrets."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent.parent
target = root / '.env'
if target.exists():
    print('.env existente preservado.')
else:
    owner, app = secrets.token_hex(24), secrets.token_hex(24)
    target.write_text(
        f'POSTGRES_ADMIN_PASSWORD={owner}\nDELTA_DB_PASSWORD={app}\n'
        f'DATABASE_URL=postgres://delta_app:{app}@127.0.0.1:5439/delta_maps\n'
        'APP_ORIGIN=http://127.0.0.1:3010\nAPP_BIND=127.0.0.1:3010\n'
        'COOKIE_SECURE=false\nREGISTRATION_ENABLED=true\nDEMO_ENABLED=true\n'
        'STORAGE_DIRECTORY=output/private\n'
    )
    target.chmod(0o600)
    print('.env local criado. Use docker compose up -d --build para iniciar.')
