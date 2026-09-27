import unittest

from fk_ik_auto_matcher.matcher import MatchService
from fk_ik_auto_matcher.models import MatchSettings


class FakeCmds:
    def __init__(self, pole=(5.0, 3.0, 0.0), preferred=(0.0, 0.0, 0.0), middle=(5.0, 0.0, 0.0)):
        self.positions = {
            "start": (0.0, 0.0, 0.0), "middle": middle,
            "end": (10.0, 0.0, 0.0), "pole": pole,
        }
        self.preferred = dict(zip("XYZ", preferred))
        self.pole_result = None

    def objExists(self, _node):
        return True

    def matchTransform(self, *_args, **_kwargs):
        pass

    def xform(self, node, query=False, worldSpace=False, translation=False, matrix=False,
              rotatePivot=False):
        if query and rotatePivot:
            return self.positions[node]
        if query and matrix:
            return (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, 0.0, 5.0, 0.0, 0.0, 1.0)
        if query and translation:
            return self.positions[node]
        if query and not translation and not matrix:
            return (0.0, 0.0, 0.0)
        if translation:
            self.pole_result = tuple(translation)
            self.positions[node] = self.pole_result

    def getAttr(self, plug, settable=False):
        if settable:
            return True
        return self.preferred[plug[-1]]

    def nodeType(self, node):
        if node in {"start", "middle", "end", "ik1", "ik2", "ik3"}:
            return "joint"
        return "transform"

    def setAttr(self, *_args):
        pass

    def undoInfo(self, **_kwargs):
        pass


def settings():
    return MatchSettings(
        start_joint="start", middle_joint="middle", end_joint="end",
        ik_controller="ik", pole_controller="pole", switch_controller="switch",
        fk_controllers=["fk1", "fk2", "fk3"], ik_joints=["ik1", "ik2", "ik3"],
        pole_distance=4.0,
    )


class StraightChainTests(unittest.TestCase):
    def test_positions_pole_by_world_rotate_pivot_not_translate(self):
        class OffsetPivotCmds(FakeCmds):
            def xform(self, node, query=False, worldSpace=False, translation=False,
                      matrix=False, rotatePivot=False):
                if query and rotatePivot:
                    value = self.positions[node]
                    return (value[0] + 10.0, value[1] + 20.0, value[2] + 30.0)
                return super().xform(
                    node, query=query, worldSpace=worldSpace,
                    translation=translation, matrix=matrix,
                    rotatePivot=rotatePivot,
                )

        cmds = OffsetPivotCmds()
        service = MatchService(cmds)
        service._set_world_pivot_position("pole", (1.0, 2.0, 3.0))
        self.assertEqual(service._world_pivot_position("pole"), (1.0, 2.0, 3.0))

    def test_reapplies_pole_world_position_after_switch_changes_parent_space(self):
        class SwitchingCmds(FakeCmds):
            def setAttr(self, plug, *_args):
                if plug == "switch.FKIK":
                    self.positions["pole"] = (5.0, 100.0, 0.0)

        cmds = SwitchingCmds(pole=(5.0, -3.0, 0.0), middle=(5.0, 1.0, 0.0))
        MatchService(cmds).fk_to_ik(settings())
        self.assertEqual(cmds.positions["pole"], (5.0, -3.0, 0.0))

    def test_bent_chain_keeps_current_pole_side(self):
        cmds = FakeCmds(pole=(5.0, -3.0, 0.0), middle=(5.0, 1.0, 0.0))
        MatchService(cmds).fk_to_ik(settings())
        self.assertEqual(cmds.pole_result, (5.0, -3.0, 0.0))

    def test_keeps_current_pole_side_for_straight_chain(self):
        cmds = FakeCmds(pole=(5.0, -3.0, 0.0), preferred=(0.0, 0.0, 20.0))
        MatchService(cmds).fk_to_ik(settings())
        self.assertEqual(cmds.pole_result, (5.0, -4.0, 0.0))

    def test_uses_preferred_angle_when_pole_has_no_direction(self):
        cmds = FakeCmds(pole=(5.0, 0.0, 0.0), preferred=(0.0, 0.0, 20.0))
        MatchService(cmds).fk_to_ik(settings())
        self.assertEqual(cmds.pole_result, (5.0, 4.0, 0.0))

    def test_ignores_unstable_pole_direction_near_chain_axis(self):
        cmds = FakeCmds(pole=(5.0, -0.001, 0.0), preferred=(0.0, 0.0, 20.0))
        MatchService(cmds).fk_to_ik(settings())
        self.assertEqual(cmds.pole_result, (5.0, 4.0, 0.0))

    def test_negative_preferred_angle_reverses_direction(self):
        cmds = FakeCmds(pole=(5.0, 0.0, 0.0), preferred=(0.0, 0.0, -20.0))
        MatchService(cmds).fk_to_ik(settings())
        self.assertEqual(cmds.pole_result, (5.0, -4.0, 0.0))

    def test_ignores_pole_parked_far_from_limb(self):
        cmds = FakeCmds(pole=(5.0, -100.0, 0.0), preferred=(0.0, 0.0, 20.0))
        service = MatchService(cmds)
        service.fk_to_ik(settings())
        self.assertEqual(cmds.pole_result, (5.0, 4.0, 0.0))
        self.assertTrue(any("parked too far" in line for line in service.last_debug_log))


class ValidationTests(unittest.TestCase):
    def test_accepts_fk_controls_as_pose_reference_fallback(self):
        value = settings()
        value.start_joint, value.middle_joint, value.end_joint = value.fk_controllers
        cmds = FakeCmds()
        self.assertEqual(MatchService(cmds).validate(value, "fk_to_ik"), [])

    def test_rejects_wrong_joint_type(self):
        cmds = FakeCmds()
        cmds.nodeType = lambda node: "transform"
        issues = MatchService(cmds).validate(settings(), "fk_to_ik")
        self.assertTrue(any("Deform Mid Jointはjointではありません" in issue
                            for issue in issues))

    def test_rejects_wrong_controller_type(self):
        cmds = FakeCmds()
        original = cmds.nodeType
        cmds.nodeType = lambda node: "nurbsCurve" if node == "pole" else original(node)
        issues = MatchService(cmds).validate(settings(), "fk_to_ik")
        self.assertTrue(any("Pole Controllerはjointまたはtransformではありません" in issue
                            for issue in issues))

    def test_rejects_pole_vector_constraint_as_controller(self):
        cmds = FakeCmds()
        original = cmds.nodeType
        cmds.nodeType = lambda node: (
            "poleVectorConstraint" if node == "pole" else original(node)
        )
        issues = MatchService(cmds).validate(settings(), "fk_to_ik")
        self.assertTrue(any(
            "Pole Controller" in issue and "poleVectorConstraint" in issue
            for issue in issues
        ))

    def test_rejects_non_settable_switch(self):
        cmds = FakeCmds()
        original = cmds.getAttr
        cmds.getAttr = lambda plug, settable=False: False if settable else original(plug)
        issues = MatchService(cmds).validate(settings(), "fk_to_ik")
        self.assertIn("FKIK Switchへ書き込めません: switch.FKIK", issues)


class IkToFkDebugTests(unittest.TestCase):
    def test_records_all_transform_measurement_stages(self):
        service = MatchService(FakeCmds())
        service.ik_to_fk(settings())
        stages = [line for line in service.last_debug_log if line[:2] in {"1.", "2.", "3.", "4."}]
        self.assertEqual(len(stages), 4)
        self.assertTrue(any("Switch変更直後" in line for line in stages))
        self.assertTrue(any("Driven Pose correction: skipped" in line
                            for line in service.last_debug_log))


if __name__ == "__main__":
    unittest.main()
