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
    # A pole almost on the start/end axis has no stable side. Normalizing that
    # tiny vector magnifies scene-evaluation noise and can send the limb across.
    _POLE_DIRECTION_TOLERANCE = 1.0e-2
    # Hidden IK controls are sometimes parked at the world origin while FK is
    # active. Such a remote position is not evidence for the desired pole side.
    _MAX_POLE_DISTANCE_RATIO = 3.0

    def __init__(self, cmds_module=None):
        if cmds_module is None:
            import maya.cmds as cmds_module
        self.cmds = cmds_module
        self.last_debug_log = []

    def validate(self, settings: MatchSettings, direction: str) -> list[str]:
        if direction == "fk_to_ik" and settings.deform_joints == settings.fk_controllers:
            joint_roles = list(zip(
                ("FK Pose Start Control", "FK Pose Mid Control", "FK Pose End Control"),
                settings.deform_joints,
            ))
        elif direction == "fk_to_ik":
            joint_roles = list(zip(
                ("Deform Start Joint", "Deform Mid Joint", "Deform End Joint"),
                settings.deform_joints,
            ))
        else:
            joint_roles = list(zip(
                ("IK Start Joint", "IK Mid Joint", "IK End Joint"),
                settings.ik_joints,
            ))
        control_roles = (
            [("IK End Control", settings.ik_controller),
             ("Pole Controller", settings.pole_controller)]
            if direction == "fk_to_ik" else
            list(zip(("FK Start Control", "FK Mid Control", "FK End Control"),
                     settings.fk_controllers))
        )
        control_roles.append(("FKIK Switch Control", settings.switch_controller))
        issues = []
        for role, node in joint_roles + control_roles:
            if not node or not self.cmds.objExists(node):
                issues.append(f"{role}が見つかりません: {node or '(未設定)'}")
                continue
            expected = "joint" if (role.endswith("Joint")) else "transform"
            allowed = {expected}
            if role.endswith(("Control", "Controller")):
                allowed.add("joint")
            try:
                actual = self.cmds.nodeType(node)
            except (AttributeError, TypeError, RuntimeError):
                actual = None
            if actual is not None and actual not in allowed:
                expected_label = "または".join(sorted(allowed))
                issues.append(f"{role}は{expected_label}ではありません: {node} ({actual})")

        if not settings.switch_plug or not self.cmds.objExists(settings.switch_plug):
            issues.append("FKIK Switch Attributeが見つかりません: " +
                          (settings.switch_plug or "(未設定)"))
        else:
            try:
                settable = bool(self.cmds.getAttr(settings.switch_plug, settable=True))
            except (AttributeError, TypeError, ValueError, RuntimeError):
                settable = False
            if not settable:
                issues.append("FKIK Switchへ書き込めません: " + settings.switch_plug)
        return issues

    def fk_to_ik(self, settings: MatchSettings) -> None:
        self._require(settings, "fk_to_ik")
        self.last_debug_log = ["FK -> IK Pole Matching"]
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
                if self._has_stable_pole_direction(current, line) and self._dot(direction, current) < 0.0:
                    direction = tuple(-value for value in direction)
            position = tuple(
                middle[i] + direction[i] / length * settings.pole_distance
                + settings.pole_offset[i] for i in range(3)
            )
            self._set_world_pivot_position(settings.pole_controller, position)
            self.cmds.setAttr(settings.switch_plug, settings.ik_value)
            # Some rigs change the pole control's parent/space when the blend
            # switches to IK. Re-apply the same world target after that DG
            # evaluation so a correct pre-switch position cannot be carried
            # away by the newly evaluated parent transform.
            try:
                switched_position = self._world_pivot_position(
                    settings.pole_controller
                )
            except (TypeError, RuntimeError):
                switched_position = ()
            if len(switched_position) == 3:
                drift = sqrt(sum(
                    (switched_position[i] - position[i]) ** 2 for i in range(3)
                ))
                self.last_debug_log.append(
                    f"Pole drift after switch: {drift:.8g}"
                )
            self._set_world_pivot_position(settings.pole_controller, position)
            final_position = self._world_pivot_position(settings.pole_controller)
            self.last_debug_log.append(
                "Pole target worldPosition=" + self._format_values(position)
            )
            self.last_debug_log.append(
                "Pole final worldPosition=" + self._format_values(final_position)
            )

    def ik_to_fk(self, settings: MatchSettings) -> None:
        self._require(settings, "ik_to_fk")
        self.last_debug_log = ["IK -> FK Transform Matching"]
        with self._undo("IK to FK Match"):
            pose_matrices = self._capture_stage(
                "1. Switch変更前 (IK Pose)", settings
            )
            for controller, joint in zip(settings.fk_controllers, settings.ik_joints):
                self.cmds.matchTransform(controller, joint, position=False, rotation=True)
            self._capture_stage("2. FK Controller Match直後", settings, pose_matrices)
            self.cmds.setAttr(settings.switch_plug, settings.fk_value)
            self._capture_stage("3. Switch変更直後", settings, pose_matrices)
            self._correct_driven_pose(settings, pose_matrices)
            self._capture_stage("4. Driven Pose補正後", settings, pose_matrices)

    def _capture_stage(self, label, settings, reference=None):
        """Record world transforms without changing the evaluated rig."""
        self.last_debug_log.append(label)
        matrices = []
        roles = ("Start", "Mid", "End")
        for role, pose, control in zip(
            roles, settings.deform_joints, settings.fk_controllers
        ):
            pose_matrix = self._world_matrix(pose)
            control_matrix = self._world_matrix(control)
            matrices.append(pose_matrix)
            self.last_debug_log.extend((
                self._transform_line(f"Pose {role} Joint", pose, pose_matrix),
                self._transform_line(f"FK {role} Control", control, control_matrix),
            ))
            if reference and pose_matrix and reference[len(matrices) - 1]:
                delta = self._matrix_delta(reference[len(matrices) - 1], pose_matrix)
                self.last_debug_log.append(
                    f"Pose {role} Delta: rotationBasis={delta[0]:.9g}, "
                    f"position={delta[1]:.9g}"
                )
        return matrices

    def _correct_driven_pose(self, settings, targets):
        """Solve FK controls from their evaluated driven joints, not node names."""
        if len(targets) != 3 or not all(targets):
            self.last_debug_log.append("Driven Pose correction: skipped (pose matrix unavailable)")
            return
        try:
            import maya.api.OpenMaya as om
        except ImportError:
            self.last_debug_log.append("Driven Pose correction: skipped (OpenMaya unavailable)")
            return

        tolerance = 1.0e-6
        rejected = set()
        for iteration in range(20):
            maximum = 0.0
            for control, driven, target_values in zip(
                settings.fk_controllers, settings.deform_joints, targets
            ):
                actual_values = self._world_matrix(driven)
                control_values = self._world_matrix(control)
                if not actual_values or not control_values:
                    continue
                before_error = self._rotation_delta(
                    target_values, actual_values, om
                )
                maximum = max(maximum, before_error)
                if control in rejected:
                    continue
                target = self._rotation_matrix(target_values, om)
                actual = self._rotation_matrix(actual_values, om)
                control_matrix = om.MMatrix(control_values)
                control_rotation = self._rotation_matrix(control_values, om)
                corrected_rotation = control_rotation * actual.inverse() * target
                corrected_transform = om.MTransformationMatrix(control_matrix)
                corrected_transform.setRotation(
                    om.MTransformationMatrix(corrected_rotation).rotation(asQuaternion=True)
                )
                self.cmds.xform(
                    control, worldSpace=True,
                    matrix=list(corrected_transform.asMatrix()),
                )
                corrected_driven = self._world_matrix(driven)
                after_error = self._rotation_delta(
                    target_values, corrected_driven, om
                ) if corrected_driven else before_error
                if after_error > before_error + tolerance:
                    # Mirrored/locked hierarchies can reject a world-space
                    # rotation solution. Never keep a correction that makes
                    # the evaluated driven pose worse.
                    self.cmds.xform(
                        control, worldSpace=True, matrix=list(control_matrix)
                    )
                    rejected.add(control)
                    self.last_debug_log.append(
                        f"Driven Pose correction rejected: {control} "
                        f"({before_error:.9g} -> {after_error:.9g})"
                    )
            if maximum <= tolerance:
                self.last_debug_log.append(
                    f"Driven Pose correction: converged in {iteration} iteration(s)"
                )
                return
        self.last_debug_log.append(
            f"Driven Pose correction: iteration limit (rotationBasis={maximum:.9g})"
        )

    @staticmethod
    def _rotation_matrix(values, om):
        """Return an orthonormal rotation matrix without scale or reflection."""
        quaternion = om.MTransformationMatrix(
            om.MMatrix(values)
        ).rotation(asQuaternion=True)
        return quaternion.asMatrix()

    @classmethod
    def _rotation_delta(cls, left, right, om):
        left_rotation = cls._rotation_matrix(left, om)
        right_rotation = cls._rotation_matrix(right, om)
        indices = (0, 1, 2, 4, 5, 6, 8, 9, 10)
        return max(abs(left_rotation[index] - right_rotation[index]) for index in indices)

    def _world_matrix(self, node):
        if not node or not self.cmds.objExists(node):
            return ()
        try:
            values = self.cmds.xform(node, query=True, worldSpace=True, matrix=True)
        except (AttributeError, TypeError, RuntimeError):
            return ()
        return tuple(float(value) for value in values) if len(values) == 16 else ()

    def _transform_line(self, role, node, matrix):
        if not matrix:
            return f"{role}: {node or '(unset)'} (world transform unavailable)"
        position = tuple(matrix[index] for index in (12, 13, 14))
        try:
            rotation = tuple(self.cmds.xform(
                node, query=True, worldSpace=True, rotation=True
            ))
        except (AttributeError, TypeError, RuntimeError):
            rotation = ()
        return (
            f"{role}: {node}\n"
            f"  worldMatrix={self._format_values(matrix)}\n"
            f"  worldPosition={self._format_values(position)}\n"
            f"  worldRotation={self._format_values(rotation)}"
        )

    @staticmethod
    def _format_values(values):
        return "[" + ", ".join(f"{float(value):.8g}" for value in values) + "]"

    @staticmethod
    def _matrix_delta(left, right):
        rotation_indices = (0, 1, 2, 4, 5, 6, 8, 9, 10)
        rotation = max(abs(left[index] - right[index]) for index in rotation_indices)
        position = sqrt(sum((left[index] - right[index]) ** 2 for index in (12, 13, 14)))
        return rotation, position

    def _straight_chain_direction(self, settings, projection, line):
        """Keep the current pole side, then fall back to the joint preferred angle."""
        direction = self._current_pole_direction(settings, projection, line)
        if self._has_stable_pole_direction(direction, line):
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
            pole = self._world_pivot_position(settings.pole_controller)
        except (TypeError, RuntimeError):
            pole = ()
        if len(pole) == 3:
            pole_from_limb = tuple(pole[i] - projection[i] for i in range(3))
            line_length_sq = self._length_sq(line)
            if (
                line_length_sq > self._EPSILON and
                self._length_sq(pole_from_limb) >
                line_length_sq * self._MAX_POLE_DISTANCE_RATIO ** 2
            ):
                self.last_debug_log.append(
                    "Current Pole direction ignored: controller is parked "
                    "too far from the limb"
                )
                return (0.0, 0.0, 0.0)
            direction = self._perpendicular(
                pole_from_limb, line
            )
            if self._length_sq(direction) > self._EPSILON:
                return direction
        return (0.0, 0.0, 0.0)

    def _world_pivot_position(self, node):
        """Return the point used by constraints, including rotatePivot offsets."""
        try:
            values = self.cmds.xform(
                node, query=True, worldSpace=True, rotatePivot=True
            )
            if values is not None and len(values) == 3:
                return tuple(float(value) for value in values)
        except (AttributeError, TypeError, RuntimeError):
            pass
        values = self.cmds.xform(
            node, query=True, worldSpace=True, translation=True
        )
        return tuple(float(value) for value in values)

    def _set_world_pivot_position(self, node, target):
        """Move a control so its world rotatePivot, not its translate, hits target."""
        try:
            pivot = self._world_pivot_position(node)
            translation = tuple(self.cmds.xform(
                node, query=True, worldSpace=True, translation=True
            ))
            adjusted = tuple(
                translation[index] + target[index] - pivot[index]
                for index in range(3)
            )
            self.cmds.xform(node, worldSpace=True, translation=adjusted)
        except (AttributeError, TypeError, RuntimeError):
            self.cmds.xform(node, worldSpace=True, translation=target)

    def _has_stable_pole_direction(self, direction, line):
        minimum_sq = self._length_sq(line) * self._POLE_DIRECTION_TOLERANCE ** 2
        return self._length_sq(direction) > max(self._EPSILON, minimum_sq)

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
