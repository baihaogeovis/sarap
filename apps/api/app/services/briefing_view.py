"""Compose a briefing from published products only.

Draft, pending QC, and withdrawn products never contribute geometries or stats.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import Area, Briefing, ImpactStat, Product, Project
from app.services.map_layers import (
    area_outline,
    display_layers_for,
    emergency_document,
    summarize_impact,
)

_LIMITATION = "统计基于雷达提取范围与专题数据叠加，建成区可能低估，不含水深和人口。"
_SOURCE = "来源：已发布产品。建议 4 小时出图是作业建议，不是合同时效。未发布或已撤回的成果不进入默认简报。"


def _published_products(db: Session, org_id: uuid.UUID, product_ids: list[Any]) -> tuple[list[Product], list[str]]:
    published: list[Product] = []
    omitted: list[str] = []
    for raw in product_ids:
        try:
            product_id = raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
        except (TypeError, ValueError):
            omitted.append(str(raw))
            continue
        row = db.get(Product, product_id)
        if row is None or row.org_id != org_id or row.deleted_at is not None or row.status != "published":
            omitted.append(str(product_id))
            continue
        published.append(row)
    return published, omitted


def _latest_published(db: Session, org_id: uuid.UUID, area: Area, scene_code: str | None) -> Product | None:
    query = db.query(Product).filter(
        Product.org_id == org_id,
        Product.area_id == area.id,
        Product.deleted_at.is_(None),
        Product.status == "published",
    )
    if scene_code:
        query = query.filter(Product.scene_code == scene_code)
    return query.order_by(Product.published_at.desc(), Product.created_at.desc()).first()


def _cross_rows(db: Session, product: Product) -> list[ImpactStat]:
    return [
        row
        for row in db.query(ImpactStat).filter(ImpactStat.product_id == product.id).all()
        if row.object_type != "extent"
    ]


def _number(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _conclusion(product: Product, impact: dict[str, Any], low: dict[str, Any]) -> str:
    if product.flood_event_status == "computed":
        area = _number(product.flood_event_ha)
        lead = f"基于已发布产品，本次淹没面积 {area} 公顷。"
    else:
        area = _number(product.extracted_water_ha if product.extracted_water_ha is not None else product.water_current_ha)
        lead = (
            f"本区域暂无已发布常年水体本底，简报只表述提取水体，不将范围称为本次淹没。"
            f"提取水体面积 {area} 公顷。"
        )
    if not impact.get("impact_configured"):
        return lead + "未配置影响对象，没有道路、居民点或行政区交叉统计。" + _LIMITATION
    roads = impact.get("affected_road_count", 0)
    length = impact.get("affected_road_length_m", 0)
    settlements = impact.get("affected_settlement_count", 0)
    admins = impact.get("affected_admin_count", 0)
    text = (
        f"{lead}受影响道路 {roads} 条、约 {length} 米；"
        f"居民点 {settlements} 个；行政区 {admins} 个。"
    )
    extra_settlements = int(low.get("affected_settlement_count") or 0) - int(settlements or 0)
    if extra_settlements > 0:
        text += f"含低置信范围时另有居民点 {extra_settlements} 个。"
    return text + _LIMITATION


def compose_product_view(
    db: Session,
    product: Product,
    area: Area | None,
    *,
    title: str,
    summary: str,
    status: str,
    briefing_id: str | None,
    omitted_product_ids: list[str],
) -> dict[str, Any]:
    cross = _cross_rows(db, product)
    impact = summarize_impact(cross)
    low = summarize_impact(cross, "including_lowconf")
    stored = summary.strip()
    generated = _conclusion(product, impact, low)
    emergency = emergency_document(db, product) or {}
    footnotes = emergency.get("footnotes") if isinstance(emergency.get("footnotes"), list) else []
    if not footnotes:
        footnotes = [_LIMITATION, "第一版不提供水深", "Sentinel-1 非小时级重访"]
    return {
        "title": title,
        "status": status,
        "briefing_id": briefing_id,
        "empty": False,
        "notice": "",
        "summary": stored or generated,
        "conclusion": stored or generated,
        "basis_label": "本次淹没" if product.flood_event_status == "computed" else "提取水体（未扣本底）",
        "flood_event_status": product.flood_event_status,
        "product": {
            "id": str(product.id),
            "title": product.title,
            "version": product.version,
            "status": product.status,
            "published_at": product.published_at.isoformat() if product.published_at else None,
            "acquisition_start": product.acquisition_start.isoformat() if product.acquisition_start else None,
            "s1_product_id": product.s1_product_id,
            "baseline_version": product.baseline_version or "",
            "baseline_version_id": str(product.baseline_version_id) if product.baseline_version_id else None,
        },
        "omitted_product_ids": omitted_product_ids,
        "stats": {
            "inundation_ha": product.flood_event_ha if product.flood_event_status == "computed" else product.extracted_water_ha,
            "inundation_label": "本次淹没面积" if product.flood_event_status == "computed" else "提取水体面积（未扣本底）",
            "water_current_ha": product.water_current_ha,
            "extracted_water_ha": product.extracted_water_ha,
            "flood_event_ha": product.flood_event_ha,
            **{key: value for key, value in impact.items() if key != "scope"},
            "including_lowconf": {key: value for key, value in low.items() if key != "scope"},
        },
        "limitation": _LIMITATION,
        "footnotes": footnotes,
        "area": {
            "id": str(area.id) if area else None,
            "name": area.name if area else "",
            "analysis_crs": area.analysis_crs if area else "",
            "aoi": area_outline(area) if area else None,
        },
        "layers": display_layers_for(db, product, area),
        "emergency_map": emergency or None,
        "source_note": _SOURCE + f" 产品「{product.title}」v{product.version}。",
    }


def empty_view(
    *,
    title: str,
    status: str,
    area: Area | None,
    notice: str,
    briefing_id: str | None = None,
    omitted_product_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "status": status,
        "briefing_id": briefing_id,
        "empty": True,
        "notice": notice,
        "summary": notice,
        "conclusion": notice,
        "basis_label": "",
        "flood_event_status": None,
        "product": None,
        "omitted_product_ids": omitted_product_ids or [],
        "stats": {"impact_configured": False},
        "limitation": _LIMITATION,
        "footnotes": [_LIMITATION, "第一版不提供水深"],
        "area": {
            "id": str(area.id) if area else None,
            "name": area.name if area else "",
            "analysis_crs": area.analysis_crs if area else "",
            "aoi": area_outline(area) if area else None,
        },
        "layers": [],
        "emergency_map": None,
        "source_note": _SOURCE,
    }


def preview_briefing(
    db: Session,
    *,
    org_id: uuid.UUID,
    project: Project,
    area: Area,
    scene_code: str | None = None,
) -> dict[str, Any]:
    product = _latest_published(db, org_id, area, scene_code)
    if product is None:
        return empty_view(
            title=f"{area.name}应急简报",
            status="preview",
            area=area,
            notice="该区域没有已发布产品。默认简报不编造淹没范围。",
        )
    if product.flood_event_status == "computed":
        title = f"{area.name}洪水应急简报"
    else:
        title = f"{area.name}水体提取简报"
    return compose_product_view(
        db,
        product,
        area,
        title=title,
        summary="",
        status="preview",
        briefing_id=None,
        omitted_product_ids=[],
    )


def briefing_document(db: Session, briefing: Briefing) -> dict[str, Any]:
    area = None
    products, omitted = _published_products(db, briefing.org_id, list(briefing.product_ids or []))
    if products and products[0].area_id is not None:
        area = db.get(Area, products[0].area_id)
    if area is None:
        area = (
            db.query(Area)
            .filter(Area.project_id == briefing.project_id, Area.deleted_at.is_(None))
            .order_by(Area.created_at.asc())
            .first()
        )
    content = briefing.content_json if isinstance(briefing.content_json, dict) else {}
    summary = str(content.get("conclusion") or content.get("summary") or "")
    if not products:
        notice = "这份简报没有可展示的已发布产品。草稿、待质检和已撤回的成果不会画进简报。"
        return empty_view(
            title=briefing.title,
            status=briefing.status,
            area=area,
            notice=notice,
            briefing_id=str(briefing.id),
            omitted_product_ids=omitted,
        )
    return compose_product_view(
        db,
        products[0],
        area,
        title=briefing.title,
        summary=summary,
        status=briefing.status,
        briefing_id=str(briefing.id),
        omitted_product_ids=omitted,
    )
