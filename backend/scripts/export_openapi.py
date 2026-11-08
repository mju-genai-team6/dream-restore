"""OpenAPI 명세를 docs/schemas/openapi.json 으로 내보낸다.
실행: backend 폴더에서  python scripts/export_openapi.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

out = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "openapi.json"
out.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {out}")
