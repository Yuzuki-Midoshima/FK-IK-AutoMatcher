"""Undo-safe FK/IK matching operations."""

from __future__ import annotations

from contextlib import contextmanager
from math import sqrt

from .models import MatchSettings


class MatchService:
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
            if line_sq <= 1.0e-12:
                raise ValueError("始点と終点が同じ位置です。")
            factor = sum((middle[i] - start[i]) * line[i] for i in range(3)) / line_sq
            projection = tuple(start[i] + line[i] * factor for i in range(3))
            direction = tuple(middle[i] - projection[i] for i in range(3))
            length = sqrt(sum(value * value for value in direction))
            if length <= 1.0e-8:
                direction, length = (0.0, 0.0, 1.0), 1.0
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
