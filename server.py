from __future__ import annotations

import sys

from app.settings import env_bool, load_env


def main() -> None:
    load_env()
    if env_bool("USE_DHWANI", False):
        from app.dhwani_legacy import main as legacy_main

        legacy_main()
        return

    try:
        from app.server import main as voice_pipeline_main
    except ModuleNotFoundError as exc:
        missing = exc.name or "a required package"
        print(f"Missing dependency: {missing}", file=sys.stderr)
        print("Run: pip install -r requirements.txt", file=sys.stderr)
        raise SystemExit(1) from exc

    voice_pipeline_main()


if __name__ == "__main__":
    main()
