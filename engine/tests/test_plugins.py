
from __future__ import annotations

from pathlib import Path

import pytest

from sarap_engine.constants import EngineError, ErrorCode
from sarap_engine.domain.algo_profile import load_default_profile
from sarap_engine.domain.pilot import PilotConfig
from sarap_engine.domain.scene import SceneMeta
from sarap_engine.plugins.base import PluginContext
from sarap_engine.plugins.pie_sar.plugin import PieSarPlugin
from sarap_engine.plugins.snap.plugin import SnapPlugin
from sarap_engine.plugins.snap.runner import (
    find_gpt,
    graph_variables,
    render_graph,
    should_apply_border_noise,
)


def _ctx(tmp_path, *, polarizations=None, input_uri=None) -> PluginContext:
    return PluginContext(
        job_id="j",
        work_dir=tmp_path,
        scene=SceneMeta(
            scene_id="s",
            polarizations=polarizations or ["VV", "VH"],
            input_uri=input_uri,
            ipf_version="3.80",
        ),
        pilot=PilotConfig.example(),
        profile=load_default_profile(),
        execution_mode="snap",
    )


def test_pie_sar_validate_and_run_not_implemented(tmp_path):
    plugin = PieSarPlugin()
    with pytest.raises(EngineError) as exc:
        plugin.validate(_ctx(tmp_path))
    assert exc.value.code == ErrorCode.PLUGIN_NOT_IMPLEMENTED
    assert "尚未实现" in exc.value.message
    assert exc.value.retryable is False
    with pytest.raises(EngineError) as exc:
        plugin.run(_ctx(tmp_path))
    assert exc.value.code == ErrorCode.PLUGIN_NOT_IMPLEMENTED


def test_snap_without_gpt_fails_clearly_and_does_not_fallback(tmp_path, monkeypatch):
    plugin = SnapPlugin(gpt_binary="gpt-definitely-missing-binary")
    ctx = _ctx(tmp_path, input_uri=str(tmp_path / "missing.SAFE"))
    # 即使造一个输入路径，没有 gpt 也应明确失败
    (tmp_path / "scene.bin").write_bytes(b"x")
    ctx = _ctx(tmp_path, input_uri=str(tmp_path / "scene.bin"))
    with pytest.raises(EngineError) as exc:
        plugin.validate(ctx)
    assert exc.value.code == ErrorCode.GPT_NOT_FOUND
    assert "不会改走 mock" in exc.value.message
    assert exc.value.retryable is False
    with pytest.raises(EngineError) as exc:
        plugin.run(ctx)
    assert exc.value.code == ErrorCode.GPT_NOT_FOUND
    # 确认环境本身也没有叫 gpt 的可执行文件，避免误走
    assert find_gpt("gpt-definitely-missing-binary") is None


def test_border_noise_wired_only_when_needed():
    profile = load_default_profile()
    vars_ = graph_variables(
        input_uri="/data/in.SAFE",
        output_uri="/data/out.tif",
        aoi_wkt="POLYGON((0 0,1 0,1 1,0 1,0 0))",
        profile=profile,
        map_projection="EPSG:4548",
        grid_origin_x=0,
        grid_origin_y=0,
        polarizations=["VV", "VH"],
    )
    xml_on = render_graph(vars_, apply_border_noise=True)
    xml_off = render_graph(vars_, apply_border_noise=False)
    assert "Remove-GRD-Border-Noise" in xml_on
    assert 'refid="Remove-GRD-Border-Noise"' in xml_on
    assert "Remove-GRD-Border-Noise" not in xml_off
    assert "${input}" not in xml_on  # 已渲染，无绝对写死模板残留变量
    assert "/data/in.SAFE" in xml_on
    assert should_apply_border_noise("3.9") is True
    assert should_apply_border_noise("3.10") is False
    assert should_apply_border_noise("3.80") is False
    assert should_apply_border_noise("3.80", force=True) is True
