"""Undo-safe FK/IK matching operations."""

from __future__ import annotations

from contextlib import contextmanager
from math import sqrt

from .models import MatchSettings


class MatchService:
    _EPSILON = 1.0e-12
    # Treat bends shallower than about 0.6 degrees as straight. Tiny numerical
    # bends are not reliable enough to choose a pole side.
    _STRAIGHT_TOLERANCE = 1.0e-2

    def __init__(self, cmds_module=None):
        if cmds_module is None:
            import maya.cmds as cmds_module
        self.cmds = cmds_module

    def validate(self, settings: MatchSettings, direction: str) -> list[str]:
        required = (
            settings.deform_joints + [settings.ik_controller, settings.pole_controller]
            if direction == "fk_to_ik" else settings.fk_controllers + settings.ik_joints
        ) + [settings.switch_controller]
        issues = [f"ノードが見つかりません: {node or '(未設定)'}"
                  for node in required if not node or not self.cmds.objExists(node)]
        if not settings.switch_plug or not self.cmds.objExists(settings.switch_plug):
            issues.append("切替属性が見つかりません: " + settings.switch_plug)
        return issues

    def fk_to_ik(self, settings: MatchSettings) -> None:
        self._require(settings, "fk_to_ik")
        with self._undo("FK to IK Match"):
            self.cmds.matchTransform(
                settings.ik_controller, settings.end_joint,
                position=True, rotation=True,
            )
            points = [tuple(self.cmds.xform(
                node, query=True, worldSpace=True, translation=True
            )) for node in settings.deform_joints]
            start, middle, end = points
            line = tuple(end[i] - start[i] for i in range(3))
            line_sq = sum(value * value for value in line)
            if line_sq <= self._EPSILON:
                raise ValueError("始点と終点が同じ位置です。")
            factor = sum((middle[i] - start[i]) * line[i] for i in range(3)) / line_sq
            projection = tuple(start[i] + line[i] * factor for i in range(3))
            direction = tuple(middle[i] - projection[i] for i in range(3))
            length = sqrt(sum(value * value for value in direction))
            if length <= sqrt(line_sq) * self._STRAIGHT_TOLERANCE:
                direction = self._straight_chain_direction(settings, projection, line)
                length = sqrt(sum(value * value for value in direction))
            else:
                current = self._current_pole_direction(settings, projection, line)
                if self._length_sq(current) > self._EPSILON and self._dot(direction, current) < 0.0:
                    direction = tuple(-value for value in direction)
            position = tuple(
                middle[i] + direction[i] / length * settings.pole_distance
                + settings.pole_offset[i] for i in range(3)
            )
            self.cmds.xform(settings.pole_controller, worldSpace=True, translation=position)
            self.cmds.setAttr(settings.switch_plug, settings.ik_value)

    def ik_to_fk(self, settings: MatchSettings) -> None:
        self._require(settings, "ik_to_fk")
        with self._undo("IK to FK Match"):
            for controller, joint in zip(settings.fk_controllers, settings.ik_joints):
                self.cmds.matchTransform(controller, joint, position=False, rotation=True)
            self.cmds.setAttr(settings.switch_plug, settings.fk_value)

    def _straight_chain_direction(self, settings, projection, line):
        """Keep the current pole side, then fall back to the joint preferred angle."""
        direction = self._current_pole_direction(settings, projection, line)
        if self._length_sq(direction) > self._EPSILON:
            return direction

        direction = self._preferred_angle_direction(settings.middle_joint, line)
        if self._length_sq(direction) > self._EPSILON:
            return direction

        axis = min(
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            key=lambda value: abs(self._dot(value, line)),
        )
        return self._cross(line, axis)

    def _current_pole_direction(self, settings, projection, line):
        try:
            pole = tuple(self.cmds.xform(
                settings.pole_controller, query=True, worldSpace=True, translation=True
            ))
        except (TypeError, RuntimeError):
            pole = ()
        if len(pole) == 3:
            direction = self._perpendicular(
                tuple(pole[i] - projection[i] for i in range(3)), line
            )
            if self._length_sq(direction) > self._EPSILON:
                return direction
        return (0.0, 0.0, 0.0)

    def _preferred_angle_direction(self, joint, line):
        try:
            preferred = tuple(float(self.cmds.getAttr(
                f"{joint}.preferredAngle{axis}"
            )) for axis in "XYZ")
            matrix = tuple(self.cmds.xform(
                joint, query=True, worldSpace=True, matrix=True
            ))
        except (TypeError, ValueError, RuntimeError):
            return (0.0, 0.0, 0.0)
        if len(matrix) != 16 or max(map(abs, preferred), default=0.0) <= self._EPSILON:
            return (0.0, 0.0, 0.0)
        index = max(range(3), key=lambda item: abs(preferred[item]))
        rotation_axis = tuple(matrix[index * 4 + item] for item in range(3))
        bend = self._cross(rotation_axis, line)
        if preferred[index] < 0.0:
            bend = tuple(-value for value in bend)
        return self._perpendicular(bend, line)

    def _perpendicular(self, vector, line):
        line_sq = self._length_sq(line)
        if line_sq <= self._EPSILON:
            return (0.0, 0.0, 0.0)
        scale = self._dot(vector, line) / line_sq
        return tuple(vector[i] - line[i] * scale for i in range(3))

    @staticmethod
    def _dot(left, right):
        return sum(left[i] * right[i] for i in range(3))

    @staticmethod
    def _cross(left, right):
        return (
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        )

    @staticmethod
    def _length_sq(vector):
        return sum(value * value for value in vector)

    def _require(self, settings, direction):
        issues = self.validate(settings, direction)
        if issues:
            raise ValueError("\n".join(issues))

    @contextmanager
    def _undo(self, name):
        self.cmds.undoInfo(openChunk=True, chunkName=name)
        try:
            yield
        finally:
            self.cmds.undoInfo(closeChunk=True)
