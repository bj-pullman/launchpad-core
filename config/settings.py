# config/settings.py

from pathlib import Path
import os

# ============================================================
# Core Project Paths
# ============================================================

# Root of repo: .../launchpad

PROJECT_ROOT = Path(__file__).resolve().parents[1]

APPS_DIR = PROJECT_ROOT / "apps"
MODULES_DIR = PROJECT_ROOT / "modules"
DOCS_DIR = PROJECT_ROOT / "docs"
TASKS_DIR = PROJECT_ROOT / "tasks"

# Runtime / writable storage (not tracked by git)

INSTANCE_DIR = PROJECT_ROOT / "instance"
LOGS_DIR = INSTANCE_DIR / "logs"
ARCHIVE_DIR = INSTANCE_DIR / "archive"

INSTANCE_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(exist_ok=True)

# ============================================================
# Environment
# ============================================================

ENV = os.getenv("LAUNCHPAD_ENV", "dev")

# ============================================================
# Snipe-IT API Settings
# ============================================================

SNIPE_URL = os.getenv(
"SNIPE_URL",
"https://technologyinventory.sheridanschools.org"
)

SNIPE_API_TOKEN = os.getenv("SNIPE_API_TOKEN", "")

# VERIFY_SSL = False only for development

VERIFY_SSL = os.getenv("VERIFY_SSL", "false").lower() == "true"

# ============================================================
# Import by Scan App
# ============================================================

IMPORT_BY_SCAN_APP_DIR = APPS_DIR / "import_by_scan"

IMPORT_BY_SCAN_INSTANCE_DIR = INSTANCE_DIR / "import_by_scan"
IMPORT_BY_SCAN_DATA_DIR = IMPORT_BY_SCAN_INSTANCE_DIR / "data"

IMPORT_BY_SCAN_INSTANCE_DIR.mkdir(exist_ok=True)
IMPORT_BY_SCAN_DATA_DIR.mkdir(exist_ok=True)

IMPORT_BY_SCAN_DB_PATH = Path(
os.getenv(
"IMPORT_BY_SCAN_DB_PATH",
IMPORT_BY_SCAN_DATA_DIR / "import_by_scan.db"
)
)

# ============================================================
# Import by Scan Defaults
# ============================================================

IMPORT_BY_SCAN_DEFAULT_MODEL_ID = 1
IMPORT_BY_SCAN_DEFAULT_STATUS_ID = 2
IMPORT_BY_SCAN_DEFAULT_LOCATION_ID = 5

# ============================================================
# Snipe Catalog App
# ============================================================

SNIPE_CATALOG_APP_DIR = APPS_DIR / "snipe_catalog"

SNIPE_CATALOG_INSTANCE_DIR = INSTANCE_DIR / "snipe_catalog"
SNIPE_CATALOG_DATA_DIR = SNIPE_CATALOG_INSTANCE_DIR / "data"

SNIPE_CATALOG_INSTANCE_DIR.mkdir(exist_ok=True)
SNIPE_CATALOG_DATA_DIR.mkdir(exist_ok=True)

SNIPE_CATALOG_DB_PATH = Path(
    os.getenv(
        "SNIPE_CATALOG_DB_PATH",
        SNIPE_CATALOG_DATA_DIR / "snipe_catalog.db"
    )
)
