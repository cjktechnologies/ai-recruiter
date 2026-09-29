"""Export the OpenAPI 3.x specification: python -m scripts.export_openapi ../docs/api/openapi.json"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.main import create_app


def main(path: str) -> None:
    spec = create_app().openapi()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    ops = sum(len(v) for v in spec["paths"].values())
    print(f"Wrote {path}: OpenAPI {spec['openapi']}, {len(spec['paths'])} paths, {ops} operations")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
