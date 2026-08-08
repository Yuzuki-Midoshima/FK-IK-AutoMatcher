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

    def xform(self, node, query=False, worldSpace=False, translation=False, matrix=False):
        if query and matrix:
            return (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, 0.0, 5.0, 0.0, 0.0, 1.0)
        if query and translation:
            return self.positions[node]
        if translation:
            self.pole_result = tuple(translation)

    def getAttr(self, plug):
        return self.preferred[plug[-1]]

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

    def test_negative_preferred_angle_reverses_direction(self):
        cmds = FakeCmds(pole=(5.0, 0.0, 0.0), preferred=(0.0, 0.0, -20.0))
        MatchService(cmds).fk_to_ik(settings())
        self.assertEqual(cmds.pole_result, (5.0, -4.0, 0.0))


if __name__ == "__main__":
    unittest.main()
