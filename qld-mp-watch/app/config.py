from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'qld_mp_watch.sqlite3'}")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
ECQ_CSV_URL = os.getenv("ECQ_CSV_URL", "")

PARLIAMENT_START = "2024-11-26"
MEMBERS_URL = "https://www.parliament.qld.gov.au/Members/Current-Members/Member-list"
HANSARD_BROWSE_URLS = [
    "https://www.parliament.qld.gov.au/Work-of-the-Assembly/Record-of-Proceedings/Browse-by-Sitting-Dates",
    "https://www.parliament.qld.gov.au/Work-of-the-Assembly/Sitting-Dates/Dates",
]
HANSARD_DOC_BASE = "https://documents.parliament.qld.gov.au/events/han"
ECQ_MAP_URL = "https://disclosures.ecq.qld.gov.au/Map"
BOUNDARY_URL = (
    "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/"
    "Boundaries/AdministrativeBoundaries/MapServer/5/query"
)
USER_AGENT = "QLD-MP-Watch/0.4 (+public-interest transparency project; respectful request rate)"
