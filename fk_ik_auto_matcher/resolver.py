"""Manifest-first and conservative naming-based rig discovery."""

from __future__ import annotations

import json
import re

from .models import MatchSettings


class RigResolver:
    MANIFEST_ATTR = "rigModuleBuilderManifest"

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
        return self._from_scene(selected)

    def _manifest_for(self, selected: str) -> dict | None:
        related = self._related_names(selected)
        best = None
        best_score = 0
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
            if score > best_score:
                best, best_score = payload, score
        return best

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
        return MatchSettings(
            start_joint=deform[0], middle_joint=deform[index], end_joint=deform[-1],
            ik_controller=str(data.get("ik_controller", "")),
            pole_controller=str(data.get("pole_controller", "")),
            switch_controller=switch_node or str(data.get("settings_controller", "")),
            fk_controllers=[fk[0], fk[index], fk[-1]],
            ik_joints=[ik[0], ik[index], ik[-1]],
            switch_attribute=switch_attr or "FKIK",
            pole_distance=float(data.get("pole_distance_multiplier", 5.0)),
            source="Rig Module Builder Manifest",
        )

    def _from_scene(self, selected: str) -> MatchSettings:
        namespace = self._leaf(selected).rsplit(":", 1)[0] if ":" in self._leaf(selected) else ""
        prefix = namespace + ":" if namespace else ""
        transforms = self.cmds.ls(prefix + "*", type="transform", long=True) or []
        joints = self.cmds.ls(prefix + "*", type="joint", long=True) or []
        fk_controls = self._ordered(self._filter(transforms, r"(^|_)FK(_|.*CTRL)"))
        ik_joints = self._ordered(self._filter(joints, r"(^|_)IK(_|.*JNT)"))
        deform = self._best_deform_chain(joints)
        ik_controls = self._filter(transforms, r"(^|_)IK(_|.*CTRL)")
        pole = self._first(transforms, r"(^|_)(PV|POLE)(_|$)")
        ik_controller = next((n for n in ik_controls if n != pole), "")
        switch_node, switch_attr = self._switch_control(transforms)
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
        return max(chains, key=len, default=[])

    def _switch_control(self, transforms):
        for node in transforms:
            for attr in self.cmds.listAttr(node, keyable=True) or []:
                if re.search(r"fk.?ik|ik.?fk", attr, re.I):
                    return node, attr
        return "", "FKIK"

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

    def _first(self, nodes, pattern):
        return next(iter(self._filter(nodes, pattern)), "")

    def _ordered(self, nodes):
        return sorted(nodes, key=lambda node: self._leaf(node).lower())

    @staticmethod
    def _leaf(node):
        return str(node).rsplit("|", 1)[-1]
