"""Locations for strategy research runtime data.

Keep generated state and reports out of source and test directories. Existing
installations may still have state in the former tests/reports location.
"""

from pathlib import Path
import shutil

from config import DATA_DIR


RESEARCH_DATA_DIR = DATA_DIR / "research"
LEGACY_RESEARCH_DIR = Path(__file__).resolve().parents[1] / "tests" / "reports" / "strategy_research"


def get_research_data_dir() -> Path:
    """Return the runtime directory, copying legacy outputs once if needed."""
    RESEARCH_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if LEGACY_RESEARCH_DIR.exists():
        for source in LEGACY_RESEARCH_DIR.iterdir():
            destination = RESEARCH_DATA_DIR / source.name
            if (
                source.is_file()
                and source.suffix in {".json", ".md", ".log"}
                and not destination.exists()
            ):
                shutil.copy2(source, destination)
    return RESEARCH_DATA_DIR
