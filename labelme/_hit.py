from __future__ import annotations

import dataclasses
import enum

import numpy as np
import numpy.typing as npt

from ._shape import Shape
from ._shape import nearest_edge_index
from ._shape import nearest_rotation_point_index
from ._shape import nearest_vertex_index


class HitKind(enum.Enum):
    VERTEX = "vertex"
    ROTATION_HANDLE = "rotation_handle"
    EDGE = "edge"
    BODY = "body"


@dataclasses.dataclass(frozen=True)
class HitTarget:
    kind: HitKind
    shape: Shape
    index: int | None


def find_hover_target(
    *,
    shapes: list[Shape],
    point: npt.NDArray[np.float64],
    scale: float,
    epsilon: float,
    point_size: int,
    priority_shape: Shape | None,
) -> HitTarget | None:
    candidates = _build_candidates(
        shapes=shapes,
        priority_shape=priority_shape,
    )

    for shape in candidates:
        idx = nearest_vertex_index(
            shape=shape, point=point, scale=scale, epsilon=epsilon
        )
        if idx is not None:
            return HitTarget(kind=HitKind.VERTEX, shape=shape, index=idx)

    for shape in candidates:
        idx = nearest_rotation_point_index(
            shape=shape, point=point, scale=scale, epsilon=epsilon
        )
        if idx is not None:
            return HitTarget(kind=HitKind.ROTATION_HANDLE, shape=shape, index=idx)

    for shape in candidates:
        if not shape.can_add_point():
            continue
        idx = nearest_edge_index(shape=shape, point=point, scale=scale, epsilon=epsilon)
        if idx is not None:
            return HitTarget(kind=HitKind.EDGE, shape=shape, index=idx)

    for shape in candidates:
        hit = is_hit_by_point(
            shape=shape,
            point=point,
            scale=scale,
            point_size=point_size,
            epsilon=epsilon,
        )
        if hit:
            return HitTarget(kind=HitKind.BODY, shape=shape, index=None)

    return None


def _build_candidates(
    *,
    shapes: list[Shape],
    priority_shape: Shape | None,
) -> list[Shape]:
    candidates: list[Shape] = []
    if priority_shape is not None and priority_shape.visible:
        candidates.append(priority_shape)
    for shape in reversed(shapes):
        if not shape.visible:
            continue
        if shape is priority_shape:
            continue
        candidates.append(shape)
    return candidates


def is_within_pick_threshold(
    *,
    a: npt.NDArray[np.float64],
    b: npt.NDArray[np.float64],
    scale: float,
    epsilon: float,
) -> bool:
    return bool(np.linalg.norm(a - b) < epsilon / scale)


def is_hit_by_point(
    *,
    shape: Shape,
    point: npt.NDArray[np.float64],
    scale: float,
    point_size: int,
    epsilon: float,
) -> bool:
    if shape.shape_type in ("line", "linestrip"):
        return (
            nearest_edge_index(shape=shape, point=point, scale=scale, epsilon=epsilon)
            is not None
        )
    if shape.shape_type == "points":
        return False
    if shape.shape_type == "point":
        if len(shape.points) == 0:
            return False
        return bool(np.linalg.norm((point - shape.points[0]) * scale) <= point_size / 2)
    if shape.mask is not None:
        raw_y = int(round(float(point[1]) - float(shape.points[0][1])))
        raw_x = int(round(float(point[0]) - float(shape.points[0][0])))
        if (
            raw_y < 0
            or raw_y >= shape.mask.shape[0]
            or raw_x < 0
            or raw_x >= shape.mask.shape[1]
        ):
            return False
        return bool(shape.mask[raw_y, raw_x])
    return _contains_point(shape=shape, point=point)


def _contains_point(*, shape: Shape, point: npt.NDArray[np.float64]) -> bool:
    points = shape.points
    if len(points) == 0:
        return False
    x, y = float(point[0]), float(point[1])
    if shape.shape_type in ("rectangle", "mask"):
        if len(points) != 2:
            return False
        x0, y0 = float(points[0][0]), float(points[0][1])
        x1, y1 = float(points[1][0]), float(points[1][1])
        return min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1)
    if shape.shape_type == "circle":
        if len(points) != 2:
            return False
        radius = float(np.linalg.norm(points[0] - points[1]))
        return bool(np.linalg.norm(point - points[0]) <= radius)
    vertices = points
    if shape.shape_type == "oriented_rectangle" and len(points) == 4:
        return _point_in_polygon(x=x, y=y, vertices=vertices)
    if len(points) < 3:
        return False
    return _point_in_polygon(x=x, y=y, vertices=vertices)


def _point_in_polygon(*, x: float, y: float, vertices: npt.NDArray[np.float64]) -> bool:
    inside = False
    previous = vertices[-1]
    for current in vertices:
        x1, y1 = float(previous[0]), float(previous[1])
        x2, y2 = float(current[0]), float(current[1])
        intersects = (y1 > y) != (y2 > y)
        if intersects and y2 != y1:
            at_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < at_x:
                inside = not inside
        previous = current
    return inside
