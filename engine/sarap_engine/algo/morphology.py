"""纯 numpy 形态学与连通域，不依赖 scipy / scikit-image / SNAP。"""

from __future__ import annotations

import numpy as np


def binary_dilation(mask: np.ndarray, size: int = 3) -> np.ndarray:
    mask = np.asarray(mask, dtype=bool)
    if size <= 1:
        return mask.copy()
    r = size // 2
    padded = np.pad(mask, r, mode="constant", constant_values=False)
    out = np.zeros_like(mask, dtype=bool)
    h, w = mask.shape
    for i in range(size):
        for j in range(size):
            out |= padded[i : i + h, j : j + w]
    return out


def binary_erosion(mask: np.ndarray, size: int = 3) -> np.ndarray:
    mask = np.asarray(mask, dtype=bool)
    if size <= 1:
        return mask.copy()
    # 边界外视为 False，因此边缘会被腐蚀
    return ~binary_dilation(~mask, size=size) & mask


def binary_opening(mask: np.ndarray, size: int = 3) -> np.ndarray:
    return binary_dilation(binary_erosion(mask, size=size), size=size)


def binary_closing(mask: np.ndarray, size: int = 3) -> np.ndarray:
    return binary_erosion(binary_dilation(mask, size=size), size=size)


def label_connected(mask: np.ndarray, connectivity: int = 8) -> tuple[np.ndarray, int]:
    """两遍并查集连通域标记。返回 labels（0=背景）、n_labels。"""
    mask = np.asarray(mask, dtype=bool)
    h, w = mask.shape
    parent = np.arange(h * w, dtype=np.int32)

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    neighbors = [(-1, 0), (0, -1)]
    if connectivity == 8:
        neighbors += [(-1, -1), (-1, 1)]

    for i in range(h):
        for j in range(w):
            if not mask[i, j]:
                continue
            idx = i * w + j
            for di, dj in neighbors:
                ni, nj = i + di, j + dj
                if 0 <= ni < h and 0 <= nj < w and mask[ni, nj]:
                    union(idx, ni * w + nj)

    labels = np.zeros((h, w), dtype=np.int32)
    remap: dict[int, int] = {}
    next_id = 1
    for i in range(h):
        for j in range(w):
            if not mask[i, j]:
                continue
            root = find(i * w + j)
            if root not in remap:
                remap[root] = next_id
                next_id += 1
            labels[i, j] = remap[root]
    return labels, next_id - 1


def remove_small_components(
    mask: np.ndarray,
    min_pixels: int,
    connectivity: int = 8,
) -> tuple[np.ndarray, np.ndarray]:
    """删除小于 min_pixels 的图斑。返回 (保留掩膜, 被删掩膜)。"""
    labels, n = label_connected(mask, connectivity=connectivity)
    kept = np.zeros_like(mask, dtype=bool)
    removed = np.zeros_like(mask, dtype=bool)
    if n == 0:
        return kept, removed
    counts = np.bincount(labels.ravel())
    for lab in range(1, n + 1):
        sel = labels == lab
        if counts[lab] >= min_pixels:
            kept[sel] = True
        else:
            removed[sel] = True
    return kept, removed


def restore_adjacent_small(
    kept: np.ndarray,
    removed: np.ndarray,
    connectivity: int = 8,
) -> tuple[np.ndarray, np.ndarray]:
    """与确定水体邻接（距离 ≤ 1 像元）的小斑可选择并回。"""
    if not removed.any() or not kept.any():
        return kept, removed
    near = binary_dilation(kept, size=3) if connectivity == 8 else None
    if connectivity != 8:
        near = binary_dilation_cross(kept)
    attach = removed & near
    if not attach.any():
        return kept, removed
    new_kept = kept | attach
    new_removed = removed & ~attach
    return new_kept, new_removed


def binary_dilation_cross(mask: np.ndarray) -> np.ndarray:
    mask = np.asarray(mask, dtype=bool)
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    h, w = mask.shape
    out = mask.copy()
    out |= padded[0:h, 1 : w + 1]
    out |= padded[2 : h + 2, 1 : w + 1]
    out |= padded[1 : h + 1, 0:w]
    out |= padded[1 : h + 1, 2 : w + 2]
    return out
