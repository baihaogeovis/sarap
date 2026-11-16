"""产品口径常量，对齐 SARAP-SPEC-FLOOD-V1 v1.1.0 / M0 冻结口径。"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class ClassCode(IntEnum):
    NODATA = 0
    NON_WATER = 1
    PERMANENT_OR_BASELINE_WATER = 2
    FLOOD_EVENT = 3
    WATER_LOWCONF = 4
    EXTRACTED_WATER = 5  # 仅无本底时的确定水体；有本底时改写 2/3，不写 5


CLASS_NAMES: dict[int, str] = {
    ClassCode.NODATA: "nodata",
    ClassCode.NON_WATER: "non_water",
    ClassCode.PERMANENT_OR_BASELINE_WATER: "permanent_or_baseline_water",
    ClassCode.FLOOD_EVENT: "flood_event",
    ClassCode.WATER_LOWCONF: "water_lowconf",
    ClassCode.EXTRACTED_WATER: "extracted_water",
}


class QcFlag(IntEnum):
    URBAN = 0
    SHADOW = 1
    LAYOVER = 2
    INCIDENCE = 3
    EDGE_MIXED = 4
    THIN_OR_SOIL = 5
    BASELINE_GAP = 6
    MMU_REMOVED = 7
    ORBIT_DEGRADED = 8


def qc_bit(flag: QcFlag | int) -> int:
    return 1 << int(flag)


QC_FLAG_NAMES = {int(f): f.name for f in QcFlag}

# 规范第 9.5 / 第 1.3 节要求写入产品的三条限制。不得声称支持水深。
LIMITATIONS: tuple[str, ...] = (
    "第一版不提供水深",
    "建成区探测能力有限",
    "Sentinel-1 非小时级重访",
)

AREA_LIMITATION = "统计基于雷达提取范围，建成区可能低估，不含水深和人口。"
EXTRACTED_WATER_AREA_LABEL = "提取水体面积（未扣本底）"
WATER_CURRENT_AREA_LABEL = "当期水体面积"
FLOOD_EVENT_AREA_LABEL = "本次淹没面积"
NO_IMPACT_ASSETS_NOTE = "未配置影响对象，不出交叉结论"

DEFAULT_ALGO_PROFILE_ID = "s1_grd_flood_v1"

# 对外建议目标 4 小时（验证前不作合同承诺）。内部 10+40+10 分钟不得当作对外 SLA。
EXTERNAL_TARGET_HOURS = 4
EXTERNAL_TARGET_MINUTES = 240
INTERNAL_BUDGET_MINUTES = {
    "prepare": 10,
    "snap_extract": 40,
    "area_ingest": 10,
}

DEFAULT_T_DEFAULT = -18.0
DEFAULT_T_CLAMP = (-23.0, -14.0)
DEFAULT_MMU_HA = 0.3
DEFAULT_SLOPE_DEG = 15.0
DEFAULT_INCIDENCE_DEG = (30.0, 45.0)
DEFAULT_T_VH_BRIGHT = -12.0
DEFAULT_PIXEL_SPACING_M = 10.0
DEFAULT_MORPH_KERNEL_PX = 3
DEFAULT_AOI_BUFFER_KM = 2.0
DEFAULT_MIN_VALID_COVERAGE = 0.05
DEFAULT_MIN_DEM_COVERAGE = 0.80
BORDER_NOISE_IPF_LT = (3, 10)

PIXEL_AREA_M2_AT_10M = 100.0


class JobStatus(StrEnum):
    ACCEPTED = "accepted"
    QUEUED = "queued"
    PREPARING = "preparing"
    SNAP_RUNNING = "snap_running"
    EXTRACTING = "extracting"
    CHANGE_DETECTING = "change_detecting"
    IMPACT_MAPPING = "impact_mapping"
    QC = "qc"
    INGESTING = "ingesting"
    SUCCEEDED = "succeeded"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PREEMPTED = "preempted"


class Priority(StrEnum):
    NORMAL = "normal"
    EMERGENCY = "emergency"


class ExecutionMode(StrEnum):
    MOCK = "mock"
    SNAP = "snap"
    PIE_SAR = "pie_sar"


class FloodEventStatus(StrEnum):
    NONE = "none"
    BASELINE_MISSING = "baseline_missing"
    COMPUTED = "computed"


class UrbanPolicy(StrEnum):
    DOWNGRADE = "downgrade"
    KEEP_WITH_FLAG = "keep_with_flag"


class ErrorCode(StrEnum):
    GPT_NOT_FOUND = "GPT_NOT_FOUND"
    GPT_CRASH = "GPT_CRASH"
    GPT_TIMEOUT = "GPT_TIMEOUT"
    INPUT_MISSING = "INPUT_MISSING"
    NO_VV = "NO_VV"
    INVALID_PARAMS = "INVALID_PARAMS"
    GRID_MISALIGNED = "GRID_MISALIGNED"
    PLUGIN_NOT_IMPLEMENTED = "PLUGIN_NOT_IMPLEMENTED"
    COVERAGE_TOO_LOW = "COVERAGE_TOO_LOW"
    DISK_ERROR = "DISK_ERROR"
    INGEST_ERROR = "INGEST_ERROR"
    CANCELLED = "CANCELLED"
    SNAP_OUTPUT_INVALID = "SNAP_OUTPUT_INVALID"
    INTERNAL = "INTERNAL"


# 瞬时错误可重试；业务错误直接 failed。
TRANSIENT_ERROR_CODES = frozenset(
    {
        ErrorCode.GPT_CRASH,
        ErrorCode.GPT_TIMEOUT,
        ErrorCode.DISK_ERROR,
        ErrorCode.INGEST_ERROR,
        ErrorCode.INTERNAL,
        ErrorCode.SNAP_OUTPUT_INVALID,
    }
)

BUSINESS_ERROR_CODES = frozenset(
    {
        ErrorCode.GPT_NOT_FOUND,  # 环境缺失，偷偷改走 mock 是禁止的，也不属于“再试一次会好”
        ErrorCode.INPUT_MISSING,
        ErrorCode.NO_VV,
        ErrorCode.INVALID_PARAMS,
        ErrorCode.GRID_MISALIGNED,
        ErrorCode.PLUGIN_NOT_IMPLEMENTED,
        ErrorCode.COVERAGE_TOO_LOW,
        ErrorCode.CANCELLED,
    }
)


class EngineError(Exception):
    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        *,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.code = ErrorCode(code)
        self.message = message
        if retryable is None:
            self.retryable = self.code in TRANSIENT_ERROR_CODES
        else:
            self.retryable = retryable
