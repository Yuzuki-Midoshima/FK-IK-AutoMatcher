import unittest

from fk_ik_auto_matcher.resolver import RigResolver


class ResolverContextTests(unittest.TestCase):
    def setUp(self):
        self.resolver = RigResolver(cmds_module=object())

    def test_selected_leg_control_filters_out_arm_nodes(self):
        nodes = [
            "|CONTROLS_GRP|FK_leg_upper_CTRL",
            "|CONTROLS_GRP|FK_leg_lower_CTRL",
            "|CONTROLS_GRP|PV_leg_CTRL",
            "|CONTROLS_GRP|FK_arm_upper_CTRL",
            "|CONTROLS_GRP|FK_arm_lower_CTRL",
            "|CONTROLS_GRP|PV_arm_CTRL",
        ]
        result = self.resolver._context_candidates(nodes, "|PV_leg_CTRL", minimum=3)
        self.assertEqual(result, nodes[:3])

    def test_camel_case_limb_name_is_recognized(self):
        nodes = ["upperLeftLeg_JNT", "lowerLeftLeg_JNT", "leftLegEnd_JNT", "spine_JNT"]
        result = self.resolver._context_candidates(nodes, "PV_leftLeg_CTRL", minimum=3)
        self.assertEqual(result, nodes[:3])

    def test_falls_back_when_context_has_too_few_candidates(self):
        nodes = ["leg_JNT", "spine_JNT", "arm_JNT"]
        result = self.resolver._context_candidates(nodes, "PV_leg_CTRL", minimum=3)
        self.assertEqual(result, nodes)


if __name__ == "__main__":
    unittest.main()
