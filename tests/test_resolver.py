import json
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

    def test_rejects_ambiguous_pole_candidates(self):
        nodes = ["PV_leftArm_CTRL", "POLE_leftArm_CTRL"]
        with self.assertRaisesRegex(ValueError, "Pole Controllerを一意に解決できません"):
            self.resolver._unique(nodes, r"(^|_)(PV|POLE)(_|$)", "Pole Controller")

    def test_rejects_equal_length_deform_chains(self):
        class Cmds:
            children = {
                "armA": ["armA_mid"], "armA_mid": ["armA_end"],
                "armB": ["armB_mid"], "armB_mid": ["armB_end"],
            }

            def listRelatives(self, node, parent=False, children=False, **_kwargs):
                if parent:
                    return [] if node in ("armA", "armB") else ["parent"]
                if children:
                    return self.children.get(node, [])
                return []

        resolver = RigResolver(cmds_module=Cmds())
        nodes = ["armA", "armA_mid", "armA_end", "armB", "armB_mid", "armB_end"]
        with self.assertRaisesRegex(ValueError, "Deform Chainを一意に解決できません"):
            resolver._best_deform_chain(nodes)

    def test_rejects_ambiguous_switch_candidates(self):
        class Cmds:
            def listAttr(self, node, keyable=False):
                return ["FKIK"] if keyable else []

        resolver = RigResolver(cmds_module=Cmds())
        with self.assertRaisesRegex(ValueError, "FKIK Switchを一意に解決できません"):
            resolver._switch_control(["settingsA_CTRL", "settingsB_CTRL"])

    def test_rejects_equal_score_manifests(self):
        payload = json.dumps({
            "created_nodes": ["selected_CTRL"],
            "module_data": {"module_type": "fkik"},
        })

        class Cmds:
            def ls(self, **_kwargs):
                return ["manifestA", "manifestB"]

            def objExists(self, _plug):
                return True

            def getAttr(self, _plug):
                return payload

            def listRelatives(self, _node, **_kwargs):
                return []

        resolver = RigResolver(cmds_module=Cmds())
        with self.assertRaisesRegex(ValueError, "Manifestを一意に解決できません"):
            resolver._manifest_for("selected_CTRL")


if __name__ == "__main__":
    unittest.main()
