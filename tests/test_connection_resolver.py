import unittest

from fk_ik_auto_matcher.connection_resolver import ConnectionResolver
from fk_ik_auto_matcher.resolver import RigResolver


class ZeldaStyleCmds:
    ik_controller = "CN_Bip001_ik_Hand_R"
    pole_controller = "CN_Bip001_pv_Arm_R"
    handle = "ikHandle_Bip001_Arm_R"
    pole_constraint = handle + "_poleVectorConstraint1"
    handle_constraint = handle + "_pointConstraint1"
    ik_joints = ["ik_UpperArm_R", "ik_Forearm_R", "ik_Hand_R"]
    fk_joints = ["fk_UpperArm_R", "fk_Forearm_R", "fk_Hand_R"]
    fk_controls = [
        "CN_Bip001_fk_UpperArm_R",
        "CN_Bip001_fk_Forearm_R",
        "CN_Bip001_fk_Hand_R",
    ]
    fk_constraints = [node + "_orientConstraint1" for node in fk_joints]
    effector = "ik_Hand_R_effector"
    switch_node = "CN_Bip001_ArmSettings_R"
    switch_plug = switch_node + ".mode"

    def __init__(self):
        self.parents = {
            self.effector: self.ik_joints[-1],
            self.ik_joints[1]: self.ik_joints[0],
            self.ik_joints[2]: self.ik_joints[1],
            self.fk_joints[1]: self.fk_joints[0],
            self.fk_joints[2]: self.fk_joints[1],
            self.pole_constraint: self.handle,
            self.handle_constraint: self.handle,
            **dict(zip(self.fk_constraints, self.fk_joints)),
        }
        self.types = {
            self.ik_controller: "transform",
            self.pole_controller: "transform",
            self.handle: "ikHandle",
            self.pole_constraint: "poleVectorConstraint",
            self.handle_constraint: "pointConstraint",
            self.effector: "ikEffector",
            self.switch_node: "transform",
            **{node: "joint" for node in self.ik_joints + self.fk_joints},
            **{node: "transform" for node in self.fk_controls},
            **{node: "orientConstraint" for node in self.fk_constraints},
        }
        self.graph = {
            self.ik_controller: [self.handle_constraint],
            self.handle_constraint: [self.ik_controller, self.handle],
            self.handle: [self.handle_constraint, self.pole_constraint],
            self.pole_constraint: [self.handle, self.pole_controller],
            self.pole_controller: [self.pole_constraint],
        }

    def objExists(self, _node):
        return True

    def nodeType(self, node):
        return self.types.get(node, "")

    def ls(self, node=None, type=None, long=False, **_kwargs):
        if type == "network":
            return []
        if type == "orientConstraint":
            return self.fk_constraints
        if type in {"parentConstraint", "pointConstraint"}:
            return []
        if node is not None and long:
            return [node]
        return []

    def listRelatives(self, node, parent=False, children=False, type=None, **_kwargs):
        result = []
        if parent and node in self.parents:
            result = [self.parents[node]]
        elif children:
            result = [child for child, value in self.parents.items() if value == node]
        if type:
            result = [item for item in result if self.nodeType(item) == type]
        return result

    def listConnections(
        self, node, source=True, destination=True, type=None, plugs=False, **_kwargs
    ):
        if source and not destination and plugs:
            base = node.split(".", 1)[0]
            if base in [self.ik_controller, self.pole_controller] + self.fk_controls:
                return [self.switch_plug]
            return []
        result = list(self.graph.get(node, []))
        if type:
            result = [item for item in result if self.nodeType(item) == type]
        return result

    def ikHandle(self, node, query=False, startJoint=False, endEffector=False):
        if node != self.handle or not query:
            return None
        if startJoint:
            return self.ik_joints[0]
        if endEffector:
            return self.effector
        return None

    def poleVectorConstraint(self, node, query=False, targetList=False):
        if node == self.pole_constraint and query and targetList:
            return [self.pole_controller]
        return []

    def pointConstraint(self, node, query=False, targetList=False):
        if node == self.handle_constraint and query and targetList:
            return [self.ik_controller]
        return []

    def orientConstraint(self, node, query=False, targetList=False):
        if node in self.fk_constraints and query and targetList:
            return [self.fk_controls[self.fk_constraints.index(node)]]
        return []

    def listAttr(self, node, userDefined=False, **_kwargs):
        if node == self.switch_node and userDefined:
            return ["mode"]
        return []


class ConnectionResolverTests(unittest.TestCase):
    def test_fk_mid_controller_anchors_its_ik_handle_through_blend_constraint(self):
        class JointControlBlendCmds(ZeldaStyleCmds):
            def ls(self, node=None, type=None, long=False, **kwargs):
                if type == "ikHandle":
                    return [self.handle]
                return super().ls(node=node, type=type, long=long, **kwargs)

            def orientConstraint(self, node, query=False, targetList=False):
                if node in self.fk_constraints and query and targetList:
                    index = self.fk_constraints.index(node)
                    return [self.fk_controls[index], self.ik_joints[index]]
                return []

        cmds = JointControlBlendCmds()
        result = ConnectionResolver(cmds).resolve(cmds.fk_controls[1])
        self.assertEqual(result.ik_joints, cmds.ik_joints)
        self.assertEqual(result.fk_controllers, cmds.fk_controls)
        self.assertTrue(any("Resolved Anchor" in line for line in result.debug_log))

    def test_resolves_zelda_style_right_arm_from_connections(self):
        cmds = ZeldaStyleCmds()
        result = ConnectionResolver(cmds).resolve(cmds.ik_controller)

        self.assertEqual(result.ik_controller, cmds.ik_controller)
        self.assertEqual(result.pole_controller, cmds.pole_controller)
        self.assertEqual(result.ik_joints, cmds.ik_joints)
        self.assertEqual(result.fk_joints, cmds.fk_joints)
        self.assertEqual(result.fk_controllers, cmds.fk_controls)
        self.assertEqual(result.switch_plug, cmds.switch_plug)
        self.assertEqual(result.source, "Connection-based Resolution")
        self.assertEqual(
            result.resolution_methods["pole_controller"],
            "Pole Vector Connection",
        )

    def test_rig_resolver_uses_connections_before_name_search(self):
        cmds = ZeldaStyleCmds()
        result = RigResolver(cmds).resolve(cmds.ik_controller)
        self.assertEqual(result.source, "Connection-based Resolution")

    def test_ambiguous_direct_pole_targets_are_rejected(self):
        cmds = ZeldaStyleCmds()
        cmds.types["other_pole"] = "transform"
        original = cmds.poleVectorConstraint
        cmds.poleVectorConstraint = lambda node, **kwargs: (
            [cmds.pole_controller, "other_pole"]
            if node == cmds.pole_constraint else original(node, **kwargs)
        )
        result = ConnectionResolver(cmds).resolve(cmds.ik_controller)
        self.assertEqual(result.pole_controller, "")
        self.assertIn("一意に解決できません", result.resolution_errors["pole_controller"])

    def test_pole_target_is_controller_not_unrelated_constraint(self):
        class Cmds(ZeldaStyleCmds):
            pole_controller = "|hero:rig|hero:PV_OFFSET|hero:Pole_CTRL"
            pole_constraint = "unrelated_node_42"

            def poleVectorConstraint(self, node, query=False, targetList=False):
                if node == self.pole_constraint and query and targetList:
                    return [self.pole_constraint, self.pole_controller]
                return []

        cmds = Cmds()
        result = ConnectionResolver(cmds)._pole_controller(cmds.handle)

        self.assertEqual(result, cmds.pole_controller)
        self.assertNotEqual(result, cmds.pole_constraint)

    def test_pole_target_falls_back_to_constraint_input_direction(self):
        class Cmds(ZeldaStyleCmds):
            pole_controller = "|hero:rig|hero:PV_OFFSET|hero:Pole_CTRL"
            pole_constraint = "unrelated_node_42"

            def poleVectorConstraint(self, _node, **_kwargs):
                return []

        cmds = Cmds()
        result = ConnectionResolver(cmds)._pole_controller(cmds.handle)

        self.assertEqual(result, cmds.pole_controller)

    def test_diana_style_branch_stops_at_ik_handle_range(self):
        class Cmds(ZeldaStyleCmds):
            ik_joints = ["Shoulder_IK", "Elbow_IK", "Wrist_IK"]
            fk_joints = ["Shoulder_FK", "Elbow_FK", "Wrist_FK"]
            fk_controls = ["Shoulder_CTRL", "Elbow_CTRL", "Wrist_CTRL"]
            fk_constraints = [node + "_controlConstraint" for node in fk_joints]
            deform = ["Shoulder", "Elbow", "Wrist"]
            blend_constraints = [node + "_blendConstraint" for node in deform]
            fingers = ["Thumb", "Index", "Middle", "Ring", "Pinky"]
            palm = "Palm"
            effector = "Wrist_effector"

            def __init__(self):
                super().__init__()
                self.parents.update({
                    self.deform[1]: self.deform[0],
                    self.deform[2]: self.deform[1],
                    self.palm: self.deform[2],
                    **{finger: self.palm for finger in self.fingers},
                    **dict(zip(self.blend_constraints, self.deform)),
                })
                self.types.update({
                    **{node: "joint" for node in self.deform + [self.palm] + self.fingers},
                    **{node: "parentConstraint" for node in self.blend_constraints},
                })

            def ls(self, node=None, type=None, long=False, **kwargs):
                if type == "parentConstraint":
                    return self.blend_constraints
                return super().ls(node, type, long, **kwargs)

            def parentConstraint(self, node, query=False, targetList=False):
                if node in self.blend_constraints and query and targetList:
                    index = self.blend_constraints.index(node)
                    return [self.ik_joints[index], self.fk_joints[index]]
                return []

        cmds = Cmds()
        result = ConnectionResolver(cmds).resolve(cmds.ik_controller)

        self.assertEqual(result.fk_joints, cmds.fk_joints)
        self.assertEqual(result.fk_controllers, cmds.fk_controls)
        self.assertEqual(result.deform_joints, cmds.deform)
        self.assertNotIn(cmds.palm, result.deform_joints)
        self.assertFalse(set(cmds.fingers) & set(result.deform_joints))

    def test_namespaced_branch_chain_uses_connection_identity(self):
        resolver = ConnectionResolver(cmds_module=object())
        self.assertTrue(
            resolver._same_node(
                "|hero:rig|hero:Shoulder_IK",
                "hero:Shoulder_IK",
            )
        )


if __name__ == "__main__":
    unittest.main()
