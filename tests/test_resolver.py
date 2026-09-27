import json
import unittest

from fk_ik_auto_matcher.resolver import RigResolver
from fk_ik_auto_matcher.models import MatchSettings


class ResolverContextTests(unittest.TestCase):
    def setUp(self):
        self.resolver = RigResolver(cmds_module=object())

    def test_scene_search_fills_only_missing_connection_fields(self):
        connected = MatchSettings(
            ik_controller="direct_ik", ik_joints=["ik_a", "ik_b", "ik_c"],
            source="Connection-based Resolution (Partial)",
            resolution_errors={"pole_controller": "not found"},
        )
        scene = MatchSettings(
            start_joint="pose_a", middle_joint="pose_b", end_joint="pose_c",
            ik_controller="named_ik", pole_controller="named_pole",
            switch_controller="settings", switch_attribute="blend",
            fk_controllers=["fk_a", "fk_b", "fk_c"],
            ik_joints=["named_a", "named_b", "named_c"],
        )
        result = self.resolver._merge_resolution(connected, scene)
        self.assertEqual(result.ik_controller, "direct_ik")
        self.assertEqual(result.ik_joints, ["ik_a", "ik_b", "ik_c"])
        self.assertEqual(result.fk_controllers, ["fk_a", "fk_b", "fk_c"])
        self.assertEqual(result.pole_controller, "named_pole")
        self.assertEqual(result.switch_plug, "settings.blend")
        self.assertNotIn("pole_controller", result.resolution_errors)

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

    def test_left_switch_wins_when_both_sides_exist(self):
        resolver = RigResolver(cmds_module=self._switch_cmds())
        result = resolver._switch_control(
            [
                "L_arm_settings_anim", "R_arm_settings_anim",
                "L_leg_settings_anim", "R_leg_settings_anim",
            ],
            "FK_L_shoulder_anim",
            ["FK_L_elbow_anim", "FK_L_wrist_anim", "FK_R_elbow_anim"],
        )
        self.assertEqual(result, ("L_arm_settings_anim", "FKIK"))

    def test_right_switch_wins_when_both_sides_exist(self):
        resolver = RigResolver(cmds_module=self._switch_cmds())
        result = resolver._switch_control(
            ["L_arm_settings_anim", "R_arm_settings_anim"],
            "FK_R_shoulder_anim",
            ["FK_R_elbow_anim", "FK_R_wrist_anim", "FK_L_elbow_anim"],
        )
        self.assertEqual(result, ("R_arm_settings_anim", "FKIK"))

    def test_arm_switch_wins_when_arm_and_leg_exist(self):
        resolver = RigResolver(cmds_module=self._switch_cmds())
        result = resolver._switch_control(
            ["L_arm_settings_anim", "L_leg_settings_anim"],
            "FK_L_shoulder_anim",
            ["FK_L_elbow_anim", "FK_L_wrist_anim"],
        )
        self.assertEqual(result, ("L_arm_settings_anim", "FKIK"))

    def test_namespace_is_preferred(self):
        resolver = RigResolver(cmds_module=self._switch_cmds())
        result = resolver._switch_control(
            ["hero:L_arm_settings_anim", "villain:L_arm_settings_anim"],
            "hero:FK_L_shoulder_anim",
            ["hero:FK_L_elbow_anim", "hero:FK_L_wrist_anim"],
        )
        self.assertEqual(result, ("hero:L_arm_settings_anim", "FKIK"))

    def test_equal_switch_scores_remain_ambiguous(self):
        resolver = RigResolver(cmds_module=self._switch_cmds())
        with self.assertRaisesRegex(ValueError, "FKIK Switchを一意に解決できません"):
            resolver._switch_control(
                ["arm_settings_A", "arm_settings_B"], "FK_shoulder_anim"
            )

    def test_single_switch_is_unchanged(self):
        resolver = RigResolver(cmds_module=self._switch_cmds())
        self.assertEqual(
            resolver._switch_control(["settings_CTRL"], "FK_L_shoulder_anim"),
            ("settings_CTRL", "FKIK"),
        )

    def test_missing_switch_reports_not_found(self):
        resolver = RigResolver(cmds_module=self._switch_cmds())
        with self.assertRaisesRegex(ValueError, "FKIK Switchが見つかりません"):
            resolver._switch_control([], "FK_L_shoulder_anim")

    def test_boss_style_left_arm_resolves_complete_settings(self):
        class Cmds:
            transforms = [
                "FK_L_shoulder_anim", "FK_L_elbow_anim", "FK_L_wrist_anim",
                "Ik_L_hand_anim", "IK_L_elbow_anim", "L_arm_settings_anim",
                "IK_L_hand_anim_const", "IK_L_wrist_jnt",
                "R_IK_wrist_orientConstraint", "R_hand_IK_parentConstraint",
                "FK_R_shoulder_anim", "FK_R_elbow_anim", "FK_R_wrist_anim",
                "Ik_R_hand_anim", "IK_R_elbow_anim", "R_arm_settings_anim",
            ]
            joints = [
                "IK_L_shoulder_jnt", "IK_L_elbow_jnt", "IK_L_wrist_jnt",
                "IK_R_shoulder_jnt", "IK_R_elbow_jnt", "IK_R_wrist_jnt",
            ]
            parents = {
                "IK_L_elbow_jnt": "IK_L_shoulder_jnt",
                "IK_L_wrist_jnt": "IK_L_elbow_jnt",
                "IK_R_elbow_jnt": "IK_R_shoulder_jnt",
                "IK_R_wrist_jnt": "IK_R_elbow_jnt",
            }

            def objExists(self, _node):
                return True

            def ls(self, _pattern=None, type=None, **_kwargs):
                if type == "network":
                    return []
                if type == "transform":
                    return self.transforms
                if type == "joint":
                    return self.joints
                return []

            def listRelatives(self, node, parent=False, children=False, **_kwargs):
                if parent:
                    value = self.parents.get(node)
                    return [value] if value else []
                if children:
                    return [child for child, value in self.parents.items() if value == node]
                return []

            def listAttr(self, node, keyable=False):
                if keyable and node.endswith("settings_anim"):
                    return ["FKIK"]
                return []

            def listConnections(self, _item):
                return []

        resolver = RigResolver(cmds_module=Cmds())
        selections = (
            "FK_L_shoulder_anim", "FK_L_elbow_anim", "FK_L_wrist_anim",
            "Ik_L_hand_anim", "IK_L_elbow_anim", "L_arm_settings_anim",
        )
        resolved = [resolver.resolve(selection) for selection in selections]
        settings = resolved[0]

        self.assertTrue(all(
            value.ik_controller == "Ik_L_hand_anim" and
            value.pole_controller == "IK_L_elbow_anim" and
            value.switch_plug == "L_arm_settings_anim.FKIK"
            for value in resolved
        ))

        self.assertEqual(settings.fk_controllers, [
            "FK_L_shoulder_anim", "FK_L_elbow_anim", "FK_L_wrist_anim",
        ])
        self.assertEqual(settings.ik_joints, [
            "IK_L_shoulder_jnt", "IK_L_elbow_jnt", "IK_L_wrist_jnt",
        ])
        self.assertEqual(settings.deform_joints, settings.fk_controllers)
        self.assertEqual(settings.ik_controller, "Ik_L_hand_anim")
        self.assertEqual(settings.pole_controller, "IK_L_elbow_anim")
        self.assertEqual(settings.switch_plug, "L_arm_settings_anim.FKIK")

    def test_pole_candidate_prefers_selected_dag_branch(self):
        resolver = RigResolver(cmds_module=self._switch_cmds())
        selected = "|rig|leftArm|FK_L_shoulder_anim"
        expected = "|rig|leftArm|IK_L_elbow_anim"
        other = "|rig|spine|IK_L_elbow_anim"

        result = resolver._unique_chain_position(
            [other, expected], 1, "Pole Controller", selected
        )

        self.assertEqual(result, expected)

    def test_named_pole_candidate_prefers_selected_side(self):
        resolver = RigResolver(cmds_module=self._switch_cmds())

        result = resolver._unique_by_context(
            ["|rig|L_arm|PV_arm_L_CTRL", "|rig|R_arm|PV_arm_R_CTRL"],
            "Pole Controller",
            "|rig|R_arm|IK_Hand_R_CTRL",
        )

        self.assertEqual(result, "|rig|R_arm|PV_arm_R_CTRL")

    def test_control_candidates_allow_joint_based_controller(self):
        class Cmds:
            @staticmethod
            def nodeType(node):
                return "joint" if node.startswith("jointPath") else "transform"

        resolver = RigResolver(cmds_module=Cmds())
        result = resolver._control_candidates(
            ["jointPath|FK_R_shoulder_anim", "controlPath|FK_R_shoulder_anim"],
            "fk",
        )

        self.assertEqual(result, [
            "jointPath|FK_R_shoulder_anim", "controlPath|FK_R_shoulder_anim",
        ])

    def test_pole_name_search_excludes_constraint_nodes(self):
        class Cmds:
            @staticmethod
            def nodeType(node):
                if node.endswith("poleVectorConstraint1"):
                    return "poleVectorConstraint"
                return "transform"

        resolver = RigResolver(cmds_module=Cmds())
        result = resolver._controller_nodes([
            "|rig|PV_OFFSET|Pole_CTRL",
            "|rig|arm_ikHandle|arm_poleVectorConstraint1",
        ])

        self.assertEqual(result, ["|rig|PV_OFFSET|Pole_CTRL"])

    @staticmethod
    def _switch_cmds():
        class Cmds:
            def listAttr(self, _node, keyable=False):
                return ["FKIK"] if keyable else []

            def listConnections(self, _item):
                return []

        return Cmds()

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


    def test_manifest_pole_constraint_resolves_to_controller(self):
        constraint = "|rig|ikHandle|arm_poleVectorConstraint"
        controller = "|rig|controls|arm_PV_CTRL"

        class Cmds:
            @staticmethod
            def nodeType(node):
                return "poleVectorConstraint" if node == constraint else "transform"

            @staticmethod
            def poleVectorConstraint(node, query=False, targetList=False):
                if node == constraint and query and targetList:
                    return ["arm_PV_CTRL"]
                return []

            @staticmethod
            def ls(node, long=False):
                if node == "arm_PV_CTRL" and long:
                    return [controller]
                return []

        payload = {
            "source_joints": ["start", "middle", "end"],
            "module_data": {
                "deform_joints": ["start", "middle", "end"],
                "fk_controllers": ["fk_start", "fk_middle", "fk_end"],
                "ik_joints": ["ik_start", "ik_middle", "ik_end"],
                "pole_controller": constraint,
            },
        }

        result = RigResolver(cmds_module=Cmds())._from_manifest(payload)

        self.assertEqual(result.pole_controller, controller)


if __name__ == "__main__":
    unittest.main()
