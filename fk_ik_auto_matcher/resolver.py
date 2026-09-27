"""Manifest-first and conservative naming-based rig discovery."""

from __future__ import annotations

import json
import re
from typing import ClassVar

from .connection_resolver import ConnectionResolver
from .models import MatchSettings


class RigResolver:
    MANIFEST_ATTR = "rigModuleBuilderManifest"
    GENERIC_NAME_PARTS: ClassVar[set[str]] = {
        "ctrl", "control", "ctl", "jnt", "joint", "grp", "group",
        "zero", "offset", "fk", "ik", "pv", "pole", "rig",
    }
    SIDE_PARTS: ClassVar[dict[str, str]] = {
        "l": "left", "lf": "left", "left": "left",
        "r": "right", "rt": "right", "right": "right",
    }
    LIMB_PARTS: ClassVar[dict[str, str]] = {
        "arm": "arm", "shoulder": "arm", "clavicle": "arm",
        "elbow": "arm", "forearm": "arm", "wrist": "arm", "hand": "arm",
        "leg": "leg", "hip": "leg", "thigh": "leg", "knee": "leg",
        "ankle": "leg", "foot": "leg", "toe": "leg",
    }
    CHAIN_POSITIONS: ClassVar[dict[str, int]] = {
        "clavicle": 0, "shoulder": 0, "hip": 0, "thigh": 0,
        "elbow": 1, "knee": 1,
        "wrist": 2, "hand": 2, "ankle": 2, "foot": 2, "toe": 2,
    }
    NON_CONTROL_PARTS: ClassVar[set[str]] = {
        "const", "constraint", "handle", "jnt", "joint", "grp", "group",
        "offset", "pad", "parent", "orient", "point", "scale",
    }

    def __init__(self, cmds_module=None):
        if cmds_module is None:
            import maya.cmds as cmds_module
        self.cmds = cmds_module

    def resolve(self, selected: str) -> MatchSettings:
        if not selected or not self.cmds.objExists(selected):
            raise ValueError("基準ノードを1つ選択してください。")
        manifest = self._manifest_for(selected)
        if manifest:
            return self._from_manifest(manifest)
        connected = ConnectionResolver(
            self.cmds, context_scorer=self._node_context_score
        ).resolve(selected)
        if connected and self._is_complete(connected):
            return connected
        try:
            scene = self._from_scene(selected)
        except ValueError:
            if connected:
                return connected
            raise
        return self._merge_resolution(connected, scene) if connected else scene

    @staticmethod
    def _is_complete(settings):
        return bool(
            all(settings.deform_joints) and all(settings.fk_controllers) and
            all(settings.ik_joints) and settings.ik_controller and
            settings.pole_controller and settings.switch_plug
        )

    @staticmethod
    def _merge_resolution(connected, scene):
        """Keep direct DG evidence and fill only unresolved fields by name search."""
        missing_switch = not connected.switch_controller
        scalar_fields = (
            "start_joint", "middle_joint", "end_joint", "ik_controller",
            "pole_controller", "switch_controller",
        )
        for field_name in scalar_fields:
            if not getattr(connected, field_name):
                setattr(connected, field_name, getattr(scene, field_name))
        for field_name in ("fk_controllers", "fk_joints", "ik_joints"):
            direct = list(getattr(connected, field_name))
            fallback = list(getattr(scene, field_name))
            size = max(len(direct), len(fallback), 3)
            direct.extend([""] * (size - len(direct)))
            fallback.extend([""] * (size - len(fallback)))
            setattr(connected, field_name, [
                direct[index] or fallback[index] for index in range(size)
            ][:3])
        if missing_switch:
            connected.switch_attribute = scene.switch_attribute

        resolved_keys = {
            "ik_controller": bool(connected.ik_controller),
            "pole_controller": bool(connected.pole_controller),
            "fk_controllers": all(connected.fk_controllers),
            "ik_joints": all(connected.ik_joints),
            "switch_plug": bool(connected.switch_plug),
            "deform_joints": all(connected.deform_joints),
        }
        for key, resolved in resolved_keys.items():
            if resolved and key in connected.resolution_errors:
                connected.resolution_errors.pop(key, None)
                connected.resolution_methods[key] = "Scene Search Fallback"
                connected.resolution_confidence[key] = "low"
        connected.source = (
            "Connection-based Resolution + Scene Search" if
            RigResolver._is_complete(connected) else
            "Connection-based Resolution + Scene Search (Partial)"
        )
        return connected

    def _manifest_for(self, selected: str) -> dict | None:
        related = self._related_names(selected)
        matches = []
        for node in self.cmds.ls(type="network", long=True) or []:
            plug = f"{node}.{self.MANIFEST_ATTR}"
            if not self.cmds.objExists(plug):
                continue
            try:
                payload = json.loads(self.cmds.getAttr(plug))
            except (TypeError, ValueError, RuntimeError):
                continue
            data = payload.get("module_data", {})
            if not (data.get("module_type") == "fkik" or
                    (data.get("fk_joints") and data.get("ik_joints"))):
                continue
            owned = set(payload.get("created_nodes", ()))
            owned.update(payload.get("source_joints", ()))
            for value in data.values():
                if isinstance(value, str):
                    owned.add(value.split(".", 1)[0])
                elif isinstance(value, list):
                    owned.update(str(item).split(".", 1)[0] for item in value)
            score = sum(self._leaf(name) in {self._leaf(item) for item in owned}
                        for name in related)
            if score > 0:
                matches.append((score, node, payload))
        if not matches:
            return None
        best_score = max(item[0] for item in matches)
        best = [item for item in matches if item[0] == best_score]
        if len(best) > 1:
            self._raise_ambiguous("Manifest", [item[1] for item in best])
        return best[0][2]

    def _from_manifest(self, payload: dict) -> MatchSettings:
        data = payload["module_data"]
        deform = list(data.get("deform_joints") or payload.get("source_joints", ()))
        fk = list(data.get("fk_controllers", ()))
        ik = list(data.get("ik_joints", ()))
        if min(len(deform), len(fk), len(ik)) < 3:
            raise ValueError("Manifestの3点チェーン情報が不足しています。")
        index = max(1, min(int(data.get("pole_joint_index", len(deform) // 2)), len(deform) - 2))
        blend = str(data.get("blend_plug", ""))
        switch_node, _, switch_attr = blend.rpartition(".")
        pole_controller = self._constraint_target(
            str(data.get("pole_controller", "")), "poleVectorConstraint"
        )
        return MatchSettings(
            start_joint=deform[0], middle_joint=deform[index], end_joint=deform[-1],
            ik_controller=str(data.get("ik_controller", "")),
            pole_controller=pole_controller,
            switch_controller=switch_node or str(data.get("settings_controller", "")),
            fk_controllers=[fk[0], fk[index], fk[-1]],
            ik_joints=[ik[0], ik[index], ik[-1]],
            switch_attribute=switch_attr or "FKIK",
            pole_distance=float(data.get("pole_distance_multiplier", 5.0)),
            source="Rig Module Builder Manifest",
        )

    def _constraint_target(self, node: str, constraint_type: str) -> str:
        """Resolve a constraint stored in place of its driving controller."""
        if not node:
            return ""
        try:
            if self.cmds.nodeType(node) != constraint_type:
                return node
        except (AttributeError, TypeError, RuntimeError):
            return node
        targets = ConnectionResolver(self.cmds)._constraint_controller_targets(node)
        if len(targets) != 1:
            return ""
        return targets[0]

    def _from_scene(self, selected: str) -> MatchSettings:
        namespace = self._leaf(selected).rsplit(":", 1)[0] if ":" in self._leaf(selected) else ""
        prefix = namespace + ":" if namespace else ""
        transforms = self.cmds.ls(prefix + "*", type="transform", long=True) or []
        joints = self.cmds.ls(prefix + "*", type="joint", long=True) or []
        transforms = self._limb_candidates(transforms, selected, minimum=3)
        joints = self._limb_candidates(joints, selected, minimum=3)
        fk_controls = self._ordered_chain(self._control_candidates(transforms, "fk"))
        ik_joints = self._ordered_chain(self._filter(joints, r"(^|_)IK(_|.*JNT)"))
        deform = self._best_deform_chain(joints)
        ik_controls = self._control_candidates(transforms, "ik")
        pole = self._unique_by_context(
            self._controller_nodes(
                self._filter(transforms, r"(^|_)(PV|POLE)(_|$)")
            ),
            "Pole Controller", selected, fk_controls + ik_joints,
        )
        if not pole:
            pole = self._unique_chain_position(
                ik_controls, 1, "Pole Controller", selected, fk_controls + ik_joints
            )
        ik_controller = self._unique_chain_position(
            [node for node in ik_controls if node != pole], 2, "IK Controller",
            selected, fk_controls + ik_joints,
        )
        if not ik_controller:
            remaining = [node for node in ik_controls if node != pole]
            ik_controller = remaining[0] if len(remaining) == 1 else ""
        switch_node, switch_attr = self._switch_control(
            transforms, selected, fk_controls + ik_joints
        )
        # Some rigs expose only their FK controls and IK driver joints. FK
        # controls are the reliable current-pose reference while in FK mode.
        if len(deform) < 3 and len(fk_controls) >= 3:
            deform = fk_controls
        if min(len(fk_controls), len(ik_joints), len(deform)) < 3:
            raise ValueError(
                "外部リグを自動判定できませんでした。詳細設定で一度登録し、JSON保存してください。"
            )
        return MatchSettings(
            start_joint=deform[0], middle_joint=deform[len(deform)//2], end_joint=deform[-1],
            ik_controller=ik_controller, pole_controller=pole,
            switch_controller=switch_node,
            fk_controllers=[fk_controls[0], fk_controls[len(fk_controls)//2], fk_controls[-1]],
            ik_joints=[ik_joints[0], ik_joints[len(ik_joints)//2], ik_joints[-1]],
            switch_attribute=switch_attr, source="Scene naming / connections",
        )

    def _best_deform_chain(self, joints):
        excluded = [n for n in joints if not re.search(r"(^|_)(FK|IK)(_|$)", self._leaf(n), re.I)]
        roots = [n for n in excluded if not (self.cmds.listRelatives(n, parent=True, type="joint") or [])]
        chains = []
        for root in roots or excluded:
            chain = [root]
            current = root
            while True:
                children = self.cmds.listRelatives(current, children=True, type="joint", fullPath=True) or []
                if len(children) != 1:
                    break
                current = children[0]
                chain.append(current)
            if len(chain) >= 3:
                chains.append(chain)
        if not chains:
            return []
        maximum = max(map(len, chains))
        longest = [chain for chain in chains if len(chain) == maximum]
        if len(longest) > 1:
            self._raise_ambiguous("Deform Chain", [chain[0] for chain in longest])
        return longest[0]

    def _switch_control(self, transforms, selected="", chain_nodes=()):
        candidates = []
        for node in transforms:
            for attr in self.cmds.listAttr(node, keyable=True) or []:
                if re.search(r"fk.?ik|ik.?fk", attr, re.I):
                    candidates.append((node, attr))
        if not candidates:
            raise ValueError("FKIK Switchが見つかりません。")
        if len(candidates) == 1:
            return candidates[0]

        context = [selected] + list(chain_nodes)
        scores = [
            (self._switch_score(node, attr, context), node, attr)
            for node, attr in candidates
        ]
        best_score = max(score for score, _node, _attr in scores)
        best = [(node, attr) for score, node, attr in scores if score == best_score]
        if len(best) > 1:
            self._raise_ambiguous(
                "FKIK Switch", [f"{node}.{attr}" for node, attr in best]
            )
        return best[0]

    def _switch_score(self, node, attr, context):
        """Score switch evidence without guessing when the evidence is tied."""
        context = [item for item in context if item]
        node_parts = self._name_parts(node)
        primary_parts = self._name_parts(context[0]) if context else set()
        context_parts = set().union(*(self._name_parts(item) for item in context))
        score = 0

        node_namespace = self._namespace(node)
        primary_namespace = self._namespace(context[0]) if context else ""
        namespaces = ({primary_namespace} if primary_namespace else
                      {self._namespace(item) for item in context if self._namespace(item)})
        if namespaces:
            score += 40 if node_namespace in namespaces else -40

        score += self._descriptor_score(
            node_parts, self._preferred_context(primary_parts, context_parts, self.SIDE_PARTS),
            self.SIDE_PARTS, 30,
        )
        score += self._descriptor_score(
            node_parts, self._preferred_context(primary_parts, context_parts, self.LIMB_PARTS),
            self.LIMB_PARTS, 25,
        )

        ignored = self.GENERIC_NAME_PARTS | set(self.SIDE_PARTS) | set(self.LIMB_PARTS)
        score += 3 * len((node_parts & context_parts) - ignored)

        if self._is_connected_to_context(node, attr, context):
            score += 20

        normalized_attr = re.sub(r"[^a-z0-9]", "", attr.lower())
        if normalized_attr in {"fkik", "ikfk"}:
            score += 10
        return score

    @staticmethod
    def _preferred_context(primary_parts, context_parts, aliases):
        """Use selection evidence first; chains only fill information it lacks."""
        return primary_parts if any(part in aliases for part in primary_parts) else context_parts

    @staticmethod
    def _descriptor_score(node_parts, context_parts, aliases, weight):
        node_values = {aliases[part] for part in node_parts if part in aliases}
        context_values = {aliases[part] for part in context_parts if part in aliases}
        if not node_values or not context_values:
            return 0
        return weight if node_values & context_values else -weight

    def _is_connected_to_context(self, node, attr, context):
        list_connections = getattr(self.cmds, "listConnections", None)
        if not list_connections:
            return False
        related = {str(item) for item in context}
        related.update(self._leaf(item) for item in context)
        try:
            connections = list_connections(f"{node}.{attr}") or [] if attr else []
            connections = list(connections) + list(list_connections(node) or [])
        except (RuntimeError, TypeError):
            return False
        return any(item in related or self._leaf(item) in related for item in connections)

    def _related_names(self, node):
        result = {node, self._leaf(node)}
        parents = self.cmds.listRelatives(node, parent=True, fullPath=True) or []
        while parents:
            node = parents[0]
            result.update((node, self._leaf(node)))
            parents = self.cmds.listRelatives(node, parent=True, fullPath=True) or []
        return result

    def _filter(self, nodes, pattern):
        return [node for node in nodes if re.search(pattern, self._leaf(node), re.I)]

    def _control_candidates(self, nodes, mode):
        """Find FK/IK controls while excluding joints, constraints, and helpers."""
        result = []
        for node in nodes:
            parts = self._name_parts(node)
            if mode not in parts or parts & self.NON_CONTROL_PARTS:
                continue
            try:
                node_type = self.cmds.nodeType(node)
            except (AttributeError, RuntimeError, TypeError):
                node_type = None
            if node_type is not None and node_type not in {"transform", "joint"}:
                continue
            if parts & {"anim", "ctrl", "control", "ctl"}:
                result.append(node)
        return result

    def _controller_nodes(self, nodes):
        """Keep only movable DAG nodes and exclude every constraint type."""
        result = []
        for node in nodes:
            try:
                node_type = self.cmds.nodeType(node)
            except (AttributeError, RuntimeError, TypeError):
                continue
            if node_type in ConnectionResolver.CONTROLLER_TYPES:
                result.append(node)
        return result

    def _first(self, nodes, pattern):
        return next(iter(self._filter(nodes, pattern)), "")

    def _unique(self, nodes, pattern, role):
        candidates = self._filter(nodes, pattern)
        if len(candidates) > 1:
            self._raise_ambiguous(role, candidates)
        return candidates[0] if candidates else ""

    def _unique_by_context(self, candidates, role, selected="", context=()):
        """Choose a unique candidate using the selected rig branch as evidence."""
        if len(candidates) < 2:
            return candidates[0] if candidates else ""
        scores = [
            (self._node_context_score(node, [selected] + list(context)), node)
            for node in candidates
        ]
        best_score = max(score for score, _node in scores)
        best = [node for score, node in scores if score == best_score]
        if len(best) > 1:
            self._raise_ambiguous(role, best)
        return best[0]

    @staticmethod
    def _raise_ambiguous(role, candidates):
        listing = "\n".join(f"- {candidate}" for candidate in candidates)
        raise ValueError(f"{role}を一意に解決できません。\n\nCandidates:\n{listing}")

    def _ordered(self, nodes):
        return sorted(nodes, key=lambda node: self._leaf(node).lower())

    def _ordered_chain(self, nodes):
        """Prefer joint hierarchy, then conventional limb landmarks."""
        if len(nodes) < 2:
            return list(nodes)
        node_set = set(nodes)
        roots = []
        for node in nodes:
            parents = self.cmds.listRelatives(
                node, parent=True, type="joint", fullPath=True
            ) or []
            if not any(parent in node_set for parent in parents):
                roots.append(node)
        chains = []
        for root in roots:
            chain = [root]
            while True:
                children = self.cmds.listRelatives(
                    chain[-1], children=True, type="joint", fullPath=True
                ) or []
                children = [child for child in children if child in node_set]
                if len(children) != 1:
                    break
                chain.append(children[0])
            if len(chain) == len(nodes):
                chains.append(chain)
        if len(chains) == 1:
            return chains[0]

        by_position = {position: [] for position in range(3)}
        for node in nodes:
            positions = {
                self.CHAIN_POSITIONS[part]
                for part in self._name_parts(node) if part in self.CHAIN_POSITIONS
            }
            if len(positions) == 1:
                by_position[positions.pop()].append(node)
        if all(len(by_position[position]) == 1 for position in range(3)):
            return [by_position[position][0] for position in range(3)]
        return self._ordered(nodes)

    def _unique_chain_position(self, nodes, position, role, selected="", context=()):
        candidates = [
            node for node in nodes
            if position in {
                self.CHAIN_POSITIONS[part]
                for part in self._name_parts(node) if part in self.CHAIN_POSITIONS
            }
        ]
        if len(candidates) > 1:
            scores = [
                (self._node_context_score(node, [selected] + list(context)), node)
                for node in candidates
            ]
            best_score = max(score for score, _node in scores)
            candidates = [node for score, node in scores if score == best_score]
            if len(candidates) > 1:
                self._raise_ambiguous(role, candidates)
        return candidates[0] if candidates else ""

    def _node_context_score(self, node, context):
        context = [item for item in context if item]
        node_parts = self._name_parts(node)
        primary_parts = self._name_parts(context[0]) if context else set()
        context_parts = set().union(*(self._name_parts(item) for item in context))
        score = 0
        if context:
            score += 10 * max(self._dag_common_prefix(node, item) for item in context)
        score += self._descriptor_score(
            node_parts, self._preferred_context(primary_parts, context_parts, self.SIDE_PARTS),
            self.SIDE_PARTS, 30,
        )
        score += self._descriptor_score(
            node_parts, self._preferred_context(primary_parts, context_parts, self.LIMB_PARTS),
            self.LIMB_PARTS, 25,
        )
        ignored = self.GENERIC_NAME_PARTS | set(self.SIDE_PARTS) | set(self.LIMB_PARTS)
        score += 3 * len((node_parts & context_parts) - ignored)
        if self._is_connected_to_context(node, "", context):
            score += 20
        return score

    @staticmethod
    def _dag_common_prefix(left, right):
        left_parts = [part for part in str(left).split("|") if part]
        right_parts = [part for part in str(right).split("|") if part]
        count = 0
        for left_part, right_part in zip(left_parts, right_parts):
            if left_part != right_part:
                break
            count += 1
        return count

    def _limb_candidates(self, nodes, selected, minimum):
        """Remove explicit namespace/side/limb conflicts with the selection."""
        selected_parts = self._name_parts(selected)
        selected_namespace = self._namespace(selected)
        selected_side = self._descriptor_values(selected_parts, self.SIDE_PARTS)
        selected_limb = self._descriptor_values(selected_parts, self.LIMB_PARTS)
        matches = []
        for node in nodes:
            parts = self._name_parts(node)
            side = self._descriptor_values(parts, self.SIDE_PARTS)
            limb = self._descriptor_values(parts, self.LIMB_PARTS)
            if selected_namespace and self._namespace(node) != selected_namespace:
                continue
            if side and selected_side and not side & selected_side:
                continue
            if limb and selected_limb and not limb & selected_limb:
                continue
            matches.append(node)
        return matches if len(matches) >= minimum else nodes

    @staticmethod
    def _descriptor_values(parts, aliases):
        return {aliases[part] for part in parts if part in aliases}

    def _context_candidates(self, nodes, selected, minimum):
        """Prefer nodes describing the same limb as the selected control."""
        selected_parts = self._name_parts(selected) - self.GENERIC_NAME_PARTS
        selected_parts = {part for part in selected_parts if len(part) >= 3}
        if not selected_parts:
            return nodes
        matches = [
            node for node in nodes
            if selected_parts & (self._name_parts(node) - self.GENERIC_NAME_PARTS)
        ]
        return matches if len(matches) >= minimum else nodes

    def _name_parts(self, node):
        leaf = self._leaf(node).rsplit(":", 1)[-1]
        leaf = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", leaf)
        return {part.lower() for part in re.split(r"[^A-Za-z0-9]+", leaf) if part}

    def _namespace(self, node):
        leaf = self._leaf(node)
        return leaf.rsplit(":", 1)[0] if ":" in leaf else ""

    @staticmethod
    def _leaf(node):
        return str(node).rsplit("|", 1)[-1]
