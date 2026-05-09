#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from workers.crawlers.ccs import crawl_ccs_2025
from workers.crawlers.ieee_sp import crawl_ieee_sp_2025
from workers.crawlers.ndss import crawl_ndss_2025
from workers.crawlers.usenix_security import crawl_usenix_security_2025


def dump_records(name: str, records: list[dict]) -> Path:
    outdir = Path(__file__).resolve().parents[2] / "data" / "raw"
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{name}.json"
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    usenix = [item.to_dict() for item in crawl_usenix_security_2025()]
    ndss = [item.to_dict() for item in crawl_ndss_2025()]
    ieee_sp = [item.to_dict() for item in crawl_ieee_sp_2025()]
    ccs = [item.to_dict() for item in crawl_ccs_2025()]

    usenix_path = dump_records("usenix_security_2025_metadata", usenix)
    ndss_path = dump_records("ndss_2025_metadata", ndss)
    ieee_sp_path = dump_records("ieee_sp_2025_metadata", ieee_sp)
    ccs_path = dump_records("acm_ccs_2025_metadata", ccs)

    print(f"USENIX records: {len(usenix)} -> {usenix_path}")
    print(f"NDSS records: {len(ndss)} -> {ndss_path}")
    print(f"IEEE S&P records: {len(ieee_sp)} -> {ieee_sp_path}")
    print(f"ACM CCS records: {len(ccs)} -> {ccs_path}")


if __name__ == "__main__":
    main()
