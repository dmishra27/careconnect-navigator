"""Public Health Scotland open data used by the waiting-times (MLOps) track.

All files are published under the UK Open Government Licence on opendata.nhs.scot.
The waiting-times file is fetched through the CKAN datastore dump, whose URL stays
the same each month (the direct download file name changes with every release).
"""

import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PORTAL = "https://www.opendata.nhs.scot"


@dataclass(frozen=True)
class Resource:
    key: str
    file_name: str
    url: str
    title: str


RESOURCES = [
    Resource(
        "ongoing_waits",
        "ongoing_waits.csv",
        f"{PORTAL}/datastore/dump/5816ec92-66bf-4033-ae55-9df45ff19d49?bom=True",
        "Stage of Treatment Waiting Times: Ongoing Waits - Long Trend",
    ),
    Resource(
        "health_boards",
        "hb14_hb19.csv",
        f"{PORTAL}/dataset/9f942fdb-e59e-44f5-b534-d6e17229cc7b/resource/"
        "652ff726-e676-4a20-abda-435b98dd7bdc/download/hb14_hb19.csv",
        "Geography Codes and Labels: Health Board 2014 - Health Board 2019",
    ),
    Resource(
        "special_boards",
        "special_health_boards.csv",
        f"{PORTAL}/dataset/65402d20-f0f1-4cee-a4f9-a960ca560444/resource/"
        "0450a5a2-f600-4569-a9ae-5d6317141899/download/special-health-boards_19022021.csv",
        "Non-standard Geography: Special Health Boards and National Facilities",
    ),
    Resource(
        "isd_boards",
        "isd_health_board_of_treatment.csv",
        f"{PORTAL}/dataset/9f942fdb-e59e-44f5-b534-d6e17229cc7b/resource/"
        "042f9b17-a42d-4112-b40b-32c094fdc01d/download/isd_health_board_of_treatment.csv",
        "Geography Codes and Labels: ISD Health Board of Treatment (S27 codes)",
    ),
    Resource(
        "specialties",
        "specialty_codes.csv",
        f"{PORTAL}/dataset/688c7ea0-4845-4b03-9df0-4149c72cb7f0/resource/"
        "6f2e3da0-b1b5-46cc-ac04-78495daedfa3/download/specialty_codes.csv",
        "Specialty Codes",
    ),
    Resource(
        "qualifiers",
        "statistical_qualifiers.csv",
        f"{PORTAL}/dataset/2b6f00ec-fee3-4828-9303-89f31b436d2a/resource/"
        "b80f9af0-b115-4245-b591-fb22775226c4/download/statisticalqualifiers24052019.csv",
        "Statistical Qualifiers",
    ),
]
BY_KEY = {r.key: r for r in RESOURCES}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "careconnect-navigator/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download(dest: Path) -> list[dict]:
    """Download every resource into ``dest``. Returns one summary dict per file."""
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for res in RESOURCES:
        data = fetch(res.url)
        (dest / res.file_name).write_bytes(data)
        out.append({"file": res.file_name, "bytes": len(data), "sha256": sha256(data)[:12]})
        print(f"  {res.file_name:<28} {len(data) / 1e6:6.2f} MB  ({res.title})")
    return out


def upload(local_dir: Path, volume_dir: str) -> None:
    """Copy downloaded files into a Unity Catalog Volume folder through the Files API."""
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    for res in RESOURCES:
        with open(local_dir / res.file_name, "rb") as f:
            w.files.upload(f"{volume_dir}/{res.file_name}", f, overwrite=True)
        print(f"  uploaded {res.file_name} -> {volume_dir}/")
