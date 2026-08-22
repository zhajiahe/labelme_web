from __future__ import annotations

import numpy as np
import pytest

from labelme._hit import HitKind
from labelme._hit import HitTarget
from labelme._hit import find_hover_target
from labelme._hit import is_within_pick_threshold
from labelme._shape import Shape

_EPSILON: float = 10.0
_SCALE: float = 1.0
_POINT_SIZE: int = 8


def _point(x: float, y: float) -> np.ndarray:
    return np.array([x, y], dtype=np.float64)


def _polygon(points: list[tuple[float, float]], *, visible: bool = True) -> Shape:
    return Shape(
        shape_type="polygon",
        points=np.array(points, dtype=np.float64),
        closed=True,
        visible=visible,
    )


def test_hit_target_frozen() -> None:
    shape = _polygon([(0, 0), (10, 0), (10, 10)])
    target = HitTarget(kind=HitKind.BODY, shape=shape, index=None)
    with pytest.raises((AttributeError, TypeError)):
        target.kind = HitKind.VERTEX  # ty: ignore[invalid-assignment]


def test_find_hover_target_empty_shapes_returns_none() -> None:
    assert (
        find_hover_target(
            shapes=[],
            point=_point(0.0, 0.0),
            scale=_SCALE,
            epsilon=_EPSILON,
            point_size=_POINT_SIZE,
            priority_shape=None,
        )
        is None
    )


def test_invisible_shapes_are_excluded() -> None:
    invisible = _polygon([(10, 10), (50, 10), (50, 50), (10, 50)], visible=False)
    assert (
        find_hover_target(
            shapes=[invisible],
            point=_point(25.0, 25.0),
            scale=_SCALE,
            epsilon=_EPSILON,
            point_size=_POINT_SIZE,
            priority_shape=None,
        )
        is None
    )


def test_visible_shape_body_hit() -> None:
    shape = _polygon([(10, 10), (50, 10), (50, 50), (10, 50)])
    result = find_hover_target(
        shapes=[shape],
        point=_point(25.0, 25.0),
        scale=_SCALE,
        epsilon=_EPSILON,
        point_size=_POINT_SIZE,
        priority_shape=None,
    )
    assert result is not None
    assert result.kind == HitKind.BODY
    assert result.shape is shape


def test_vertex_match_beats_body() -> None:
    shape = _polygon([(10, 10), (50, 10), (50, 50), (10, 50)])
    result = find_hover_target(
        shapes=[shape],
        point=_point(10.0, 10.0),
        scale=_SCALE,
        epsilon=_EPSILON,
        point_size=_POINT_SIZE,
        priority_shape=None,
    )
    assert result is not None
    assert result.kind == HitKind.VERTEX
    assert result.index == 0


def test_edge_hit_on_polygon() -> None:
    shape = _polygon([(10, 10), (90, 10), (90, 50), (10, 50)])
    result = find_hover_target(
        shapes=[shape],
        point=_point(50.0, 10.0),
        scale=_SCALE,
        epsilon=_EPSILON,
        point_size=_POINT_SIZE,
        priority_shape=None,
    )
    assert result is not None
    assert result.kind == HitKind.EDGE


def test_priority_shape_is_checked_first() -> None:
    shape_a = _polygon([(10, 10), (50, 10), (50, 50), (10, 50)])
    shape_b = _polygon([(10, 10), (80, 10), (80, 80), (10, 80)])
    result = find_hover_target(
        shapes=[shape_b, shape_a],
        point=_point(10.0, 10.0),
        scale=_SCALE,
        epsilon=_EPSILON,
        point_size=_POINT_SIZE,
        priority_shape=shape_a,
    )
    assert result is not None
    assert result.shape is shape_a


def test_reverse_paint_order_topmost_body_wins() -> None:
    shape_a = _polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    shape_b = _polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    result = find_hover_target(
        shapes=[shape_a, shape_b],
        point=_point(50.0, 50.0),
        scale=_SCALE,
        epsilon=_EPSILON,
        point_size=_POINT_SIZE,
        priority_shape=None,
    )
    assert result is not None
    assert result.shape is shape_b


def test_is_within_pick_threshold_strictly_less_than() -> None:
    assert (
        is_within_pick_threshold(
            a=_point(0.0, 0.0), b=_point(9.9, 0.0), scale=_SCALE, epsilon=_EPSILON
        )
        is True
    )
    assert (
        is_within_pick_threshold(
            a=_point(0.0, 0.0), b=_point(10.0, 0.0), scale=_SCALE, epsilon=_EPSILON
        )
        is False
    )
