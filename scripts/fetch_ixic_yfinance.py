"""Website-compatible replacement for the supplied IXIC CSV downloader."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.pipeline.nasdaq_data import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main(default_asset='US_IXIC'))
