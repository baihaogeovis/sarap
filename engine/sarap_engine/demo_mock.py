"""一键 mock 空跑：提交任务 → 跑到 succeeded（入库 mock）→ 打印产品清单。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sarap_engine.config import Settings
from sarap_engine.orchestration.store import JobStore


def _payload(with_baseline: bool) -> dict:
    now = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
    ready = datetime(2026, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
    return {
        "scene_id": "S1A_IW_GRD_DEMO_20260701T1000",
        "pilot_id": "pilot_demo",
        "execution_mode": "mock",
        "priority": "normal",
        "data_ready_at": ready,
        "use_synthetic_baseline": with_baseline,
        "baseline_version_id": "v2026.06.01" if with_baseline else None,
        "baseline_type": "permanent_water" if with_baseline else None,
        "scene": {
            "scene_id": "S1A_IW_GRD_DEMO_20260701T1000",
            "platform": "S1A",
            "mode": "IW",
            "product_level": "GRD",
            "polarizations": ["VV", "VH"],
            "pass_direction": "ASCENDING",
            "ipf_version": "3.80",
            "orbit_type": "precise",
            "acquisition_start": now,
            "acquisition_end": datetime(2026, 7, 1, 10, 0, 25, tzinfo=timezone.utc),
            "data_ready_at": ready,
        },
        "pilot": {
            "pilot_id": "pilot_demo",
            "name": "示例区域",
            "analysis_crs": "EPSG:4548",
            "grid": {"res_m": 10, "origin_x": 0, "origin_y": 0, "width": 80, "height": 80},
            "sla_minutes": 240,
        },
    }


def run_demo(work_dir: Path | None = None, *, with_baseline: bool = False) -> dict:
    from sarap_engine.api.service import EngineService
    from sarap_engine.orchestration.worker import Worker
    from sarap_engine.products.ingest import IngestClient

    work_dir = work_dir or (Path.cwd() / "data" / "engine-demo")
    work_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        mode="mock",
        work_dir=work_dir,
        db_url="sqlite:///" + str((work_dir / "jobs.sqlite").resolve()),
        ingest_mode="mock",
        run_inline=True,
    )
    store = JobStore(settings.db_url)
    ingest = IngestClient("http://ingest.invalid/products", mode="mock")
    worker = Worker(store, settings, ingest_client=ingest)
    service = EngineService(store, settings, worker)
    data, _ = service.submit(_payload(with_baseline))
    return data


def main() -> None:
    with_baseline = "--with-baseline" in sys.argv
    data = run_demo(with_baseline=with_baseline)
    print(json.dumps({
        "job_id": data["id"],
        "status": data["status"],
        "error_code": data.get("error_code"),
        "error_message": data.get("error_message"),
        "product_id": data.get("product_id"),
        "data_ready_at": data.get("data_ready_at"),
        "submitted_at": data.get("submitted_at"),
        "processed_at": data.get("processed_at"),
        "flood_event_status": (data.get("product") or {}).get("metadata", {}).get("flood_event_status")
        if data.get("product")
        else None,
        "layers": [
            {"name": ly.get("name"), "uri": ly.get("uri"), "empty": ly.get("empty")}
            for ly in ((data.get("product") or {}).get("layers") or [])
        ],
        "metadata_area": {
            k: (data.get("product") or {}).get("metadata", {}).get(k)
            for k in (
                "extracted_water_ha",
                "extracted_water_area_label",
                "water_current_ha",
                "flood_event_ha",
                "limitations",
            )
        },
    }, ensure_ascii=False, indent=2, default=str))
    if data.get("status") != "succeeded":
        sys.exit(1)


if __name__ == "__main__":
    main()
