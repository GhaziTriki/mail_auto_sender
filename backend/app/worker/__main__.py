import sys

from ..config import get_settings
from ..crypto import validate_secret_key
from ..db import ensure_indexes
from ..errors import ConfigError
from ..logging import setup_logging
from .loop import run_forever


def main() -> None:
    setup_logging()
    try:
        validate_secret_key(get_settings().secret_key)
    except ConfigError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)
    ensure_indexes()
    run_forever()


if __name__ == "__main__":
    main()
