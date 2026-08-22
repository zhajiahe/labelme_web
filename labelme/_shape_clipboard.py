from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable

from ._shape import Shape


class _Signal:
    def __init__(self) -> None:
        self._handlers: list[Callable[[bool], None]] = []

    def connect(self, handler: Callable[[bool], None]) -> None:
        self._handlers.append(handler)

    def emit(self, value: bool) -> None:
        for handler in self._handlers:
            handler(value)


class ShapeClipboard:
    def __init__(self) -> None:
        self._buffer: tuple[Shape, ...] = ()
        self.availability_changed = _Signal()

    def store(self, shapes: Iterable[Shape]) -> None:
        snapshot = tuple(shape.copy() for shape in shapes)
        had_content = bool(self._buffer)
        self._buffer = snapshot
        if had_content != bool(snapshot):
            self.availability_changed.emit(bool(snapshot))

    def paste(self) -> list[Shape]:
        return [shape.copy() for shape in self._buffer]
