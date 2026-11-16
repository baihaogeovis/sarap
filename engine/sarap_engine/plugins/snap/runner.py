"""渲染 SNAP Graph 并调用 gpt。系统找不到 gpt 时给出明确错误，绝不偷偷改走 mock。"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from jinja2 import Environment, StrictUndefined

from sarap_engine.constants import BORDER_NOISE_IPF_LT, EngineError, ErrorCode
from sarap_engine.domain.algo_profile import AlgoProfile, packaged_graph_template_path


def parse_ipf(version: str | None) -> tuple[int, ...]:
    if not version:
        return (0,)
    parts: list[int] = []
    for p in str(version).strip().split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        if digits == "":
            break
        parts.append(int(digits))
    return tuple(parts) if parts else (0,)


def should_apply_border_noise(
    ipf_version: str | None,
    *,
    force: bool = False,
    threshold: tuple[int, ...] = BORDER_NOISE_IPF_LT,
) -> bool:
    if force:
        return True
    return parse_ipf(ipf_version) < tuple(threshold)


def find_gpt(binary: str = "gpt") -> str | None:
    if os.path.isabs(binary) and Path(binary).is_file() and os.access(binary, os.X_OK):
        return binary
    return shutil.which(binary)


def _jinja_env() -> Environment:
    return Environment(
        variable_start_string="${",
        variable_end_string="}",
        undefined=StrictUndefined,
        autoescape=False,
    )


def _set_source_ref(root: ET.Element, node_id: str, refid: str) -> None:
    for node in root.findall("node"):
        if node.get("id") != node_id:
            continue
        sources = node.find("sources")
        if sources is None:
            sources = ET.SubElement(node, "sources")
        src = sources.find("sourceProduct")
        if src is None:
            src = ET.SubElement(sources, "sourceProduct")
        src.set("refid", refid)
        return
    raise KeyError(node_id)


def _remove_node(root: ET.Element, node_id: str) -> None:
    for node in list(root.findall("node")):
        if node.get("id") == node_id:
            root.remove(node)


def wire_border_noise(xml_text: str, enabled: bool) -> str:
    """
    官方模板默认 ThermalNoiseRemoval 接 Apply-Orbit-File，同时保留 BorderNoise 节点。
    启用时：把 ThermalNoiseRemoval 的源改接到 Remove-GRD-Border-Noise。
    关闭时：删除 Remove-GRD-Border-Noise 节点，避免 SNAP 执行未接入路径的节点。
    """
    root = ET.fromstring(xml_text)
    if enabled:
        _set_source_ref(root, "ThermalNoiseRemoval", "Remove-GRD-Border-Noise")
    else:
        _remove_node(root, "Remove-GRD-Border-Noise")
        _set_source_ref(root, "ThermalNoiseRemoval", "Apply-Orbit-File")
    return ET.tostring(root, encoding="unicode")


def render_graph(
    context: dict[str, Any],
    *,
    template_path: Path | None = None,
    apply_border_noise: bool = False,
) -> str:
    path = template_path or packaged_graph_template_path()
    if not path.is_file():
        raise EngineError(ErrorCode.INPUT_MISSING, f"SNAP 图模板不存在: {path}", retryable=False)
    env = _jinja_env()
    tmpl = env.from_string(path.read_text(encoding="utf-8"))
    rendered = tmpl.render(**context)
    return wire_border_noise(rendered, apply_border_noise)


def graph_variables(
    *,
    input_uri: str,
    output_uri: str,
    aoi_wkt: str,
    profile: AlgoProfile,
    map_projection: str,
    grid_origin_x: float,
    grid_origin_y: float,
    polarizations: list[str],
) -> dict[str, Any]:
    pols = [p.upper() for p in polarizations] or ["VV"]
    has_vh = "VH" in pols
    pol_list = ",".join(p for p in ("VV", "VH") if p in pols) or "VV"
    intensity = "Intensity_VV,Intensity_VH" if has_vh else "Intensity_VV"
    sigma0 = "Sigma0_VV,Sigma0_VH" if has_vh else "Sigma0_VV"
    nodata_sea = "true" if profile.snap.mask_sea_nodata else "false"
    return {
        "input": input_uri,
        "output": output_uri,
        "aoiWkt": aoi_wkt,
        "orbitType": profile.snap.orbit_type,
        "demName": profile.snap.dem_name,
        "mapProjection": map_projection,
        "pixelSpacing": profile.snap.pixel_spacing_m,
        "gridOriginX": grid_origin_x,
        "gridOriginY": grid_origin_y,
        "polarisationList": pol_list,
        "intensityBands": intensity,
        "sigma0LinearBands": sigma0,
        "nodataValueAtSea": nodata_sea,
    }


@dataclass
class GptRunResult:
    returncode: int
    stdout: str
    stderr: str
    graph_path: Path
    output: Path


def run_gpt(
    graph_xml: str,
    work_dir: Path,
    *,
    gpt_binary: str = "gpt",
    timeout: float = 2400.0,
) -> GptRunResult:
    gpt = find_gpt(gpt_binary)
    if not gpt:
        raise EngineError(
            ErrorCode.GPT_NOT_FOUND,
            f"生产模式 snap 需要 SNAP gpt，但系统找不到可执行文件 {gpt_binary!r}。"
            "不会改走 mock 插件。请安装 SNAP 并确保 gpt 在 PATH 中，或改用 execution_mode=mock / SARAP_ENGINE_MODE=mock。",
            retryable=False,
        )
    work_dir.mkdir(parents=True, exist_ok=True)
    graph_path = work_dir / "s1_grd_flood_v1.resolved.xml"
    graph_path.write_text(graph_xml, encoding="utf-8")
    try:
        proc = subprocess.run(
            [gpt, str(graph_path)],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise EngineError(
            ErrorCode.GPT_TIMEOUT,
            f"gpt 超时（{timeout}s）",
            retryable=True,
        ) from exc
    except OSError as exc:
        raise EngineError(ErrorCode.GPT_CRASH, f"无法启动 gpt: {exc}", retryable=True) from exc

    log = work_dir / "gpt.log"
    log.write_text(
        f"returncode={proc.returncode}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}\n",
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise EngineError(
            ErrorCode.GPT_CRASH,
            f"gpt 退出码 {proc.returncode}: {(proc.stderr or proc.stdout)[:500]}",
            retryable=True,
        )
    return GptRunResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        graph_path=graph_path,
        output=work_dir,
    )
