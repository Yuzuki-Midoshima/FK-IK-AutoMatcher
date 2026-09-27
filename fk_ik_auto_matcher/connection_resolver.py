"""Conservative FK/IK discovery from Maya DG and DAG relationships."""

from __future__ import annotations

from collections import defaultdict, deque

from .models import MatchSettings


class ConnectionResolver:
    """Resolve a complete match setup without relying on a naming convention."""

    CONSTRAINT_TYPES = (
        "pointConstraint", "parentConstraint", "orientConstraint",
        "poleVectorConstraint",
    )
    FK_CONSTRAINT_TYPES = ("orientConstraint", "parentConstraint")
    CONTROLLER_TYPES = {"transform", "joint"}

    def __init__(self, cmds_module, context_scorer=None):
        self.cmds = cmds_module
        self.context_scorer = context_scorer or (lambda _node, _context: 0)
        self.debug_log = []

    def resolve(self, selected: str) -> MatchSettings | None:
        self.debug_log = [f"Selected Node: {selected}"]
        errors = {}
        try:
            handle = self._ik_handle(selected)
        except ValueError as error:
            self._log(f"IK Handle Reject Reason: {error}")
            return None
        if not handle:
            return None
        self._log(f"Detected IK Handle: {handle}")

        ik_joints = self._ik_chain(handle)
        self._log("IK Handle Chain: " + " -> ".join(ik_joints))
        try:
            pole = self._pole_controller(handle)
        except ValueError as error:
            pole = ""
            errors["pole_controller"] = str(error)
            self._log(f"Pole Controller Reject Reason: {error}")
        try:
            ik_controller = self._ik_controller(handle, selected, pole)
        except ValueError as error:
            ik_controller = ""
            errors["ik_controller"] = str(error)
            self._log(f"IK End Controller Reject Reason: {error}")
        if not ik_joints:
            errors["ik_joints"] = "IK Handleから3点Joint Chainを取得できません。"

        fk_joints, fk_controllers, connected_deform = [], [], []
        if ik_joints:
            try:
                fk_joints, fk_controllers, connected_deform = self._fk_chain(
                    selected, ik_joints
                )
            except ValueError as error:
                errors["fk_controllers"] = str(error)
                self._log(f"FK Constraint Chain Reject Reason: {error}")
        if not fk_controllers and "fk_controllers" not in errors:
            errors["fk_controllers"] = "FK Constraint Chainを解決できません。"

        deform = connected_deform
        if not deform and ik_joints and fk_joints:
            deform = self._deform_chain(ik_joints, fk_joints)
        try:
            switch = self._shared_switch(
                [ik_controller, pole] + fk_controllers,
                self._constraints_for_nodes(ik_joints + fk_joints),
            )
        except ValueError as error:
            switch = ""
            errors["switch_plug"] = str(error)
            self._log(f"FKIK Switch Reject Reason: {error}")
        if not switch and "switch_plug" not in errors:
            errors["switch_plug"] = "共有接続からFKIK Switchを取得できません。"
        switch_node, _, switch_attr = switch.rpartition(".")
        pose_chain = deform or fk_joints
        methods = {
            "ik_controller": "IK Handle Connection",
            "pole_controller": "Pole Vector Connection",
            "ik_joints": "IK Handle Joint Chain",
            "fk_controllers": "Constraint Connection",
            "fk_joints": "Constraint Driven Joint Chain",
            "switch_plug": "Shared Connection",
            "deform_joints": (
                "FK/IK Constraint Connection" if deform else
                "FK Joint Connection Fallback"
            ),
        }
        confidence = {
            "ik_controller": "high",
            "pole_controller": "high",
            "ik_joints": "high",
            "fk_controllers": "high",
            "fk_joints": "high",
            "switch_plug": "high",
            "deform_joints": "high" if deform else "medium",
        }
        complete = bool(
            len(pose_chain) >= 3 and ik_controller and pole and
            len(fk_controllers) >= 3 and len(ik_joints) >= 3 and switch
        )
        return MatchSettings(
            start_joint=pose_chain[0] if pose_chain else "",
            middle_joint=pose_chain[len(pose_chain) // 2] if pose_chain else "",
            end_joint=pose_chain[-1] if pose_chain else "",
            ik_controller=ik_controller,
            pole_controller=pole,
            switch_controller=switch_node,
            fk_controllers=self._three_or_empty(fk_controllers),
            fk_joints=self._three_or_empty(fk_joints),
            ik_joints=self._three_or_empty(ik_joints),
            switch_attribute=switch_attr or "FKIK",
            source=("Connection-based Resolution" if complete else
                    "Connection-based Resolution (Partial)"),
            resolution_methods=methods,
            resolution_confidence=confidence,
            resolution_errors=errors,
            debug_log=list(self.debug_log),
        )

    def _ik_handle(self, selected):
        anchored = self._ik_handles_from_fk_anchor(selected)
        if anchored:
            self._log(
                "Resolved Anchor: selected FK constraint -> IK Joint -> IK Handle"
            )
            return self._unique_scored(anchored, "IK Handle", [selected])
        distances = self._graph_distances(selected, maximum_depth=4)
        candidates = [
            (distance, node) for node, distance in distances.items()
            if self._node_type(node) == "ikHandle"
        ]
        if not candidates:
            candidates = [(99, node) for node in self._ls(type="ikHandle")]
        if not candidates:
            return ""
        nearest = min(distance for distance, _node in candidates)
        candidates = [node for distance, node in candidates if distance == nearest]
        return self._unique_scored(candidates, "IK Handle", [selected])

    def _ik_handles_from_fk_anchor(self, selected):
        """Find the limb handle through a selected FK blend-constraint target."""
        selected_names = self._long_names([selected]) or [selected]
        selected_node = selected_names[0]
        opposite_joints = []
        for constraint_type in self.FK_CONSTRAINT_TYPES:
            for constraint in self._ls(type=constraint_type):
                targets = self._constraint_targets(constraint)
                if not any(self._same_node(target, selected_node) for target in targets):
                    continue
                opposite_joints.extend(
                    target for target in targets
                    if not self._same_node(target, selected_node) and
                    self._node_type(target) == "joint"
                )
        if not opposite_joints:
            return []

        handles = []
        for handle in self._ls(type="ikHandle"):
            chain = self._ik_chain(handle)
            if any(
                self._same_node(joint, target)
                for joint in chain for target in opposite_joints
            ):
                handles.append(handle)
        return self._long_names(self._unique_nodes(handles))

    def _ik_chain(self, handle):
        try:
            start = self.cmds.ikHandle(handle, query=True, startJoint=True)
            effector = self.cmds.ikHandle(handle, query=True, endEffector=True)
        except (AttributeError, TypeError, RuntimeError):
            return []
        if not start or not effector:
            return []
        start_names = self._long_names([start])
        effector_names = self._long_names([effector])
        start = start_names[0] if start_names else start
        effector = effector_names[0] if effector_names else effector
        parents = self._relatives(effector, parent=True, type="joint", fullPath=True)
        end = parents[0] if len(parents) == 1 else ""
        if not end:
            return []
        chain = [end]
        while chain[-1] != start:
            parents = self._relatives(
                chain[-1], parent=True, type="joint", fullPath=True
            )
            if len(parents) != 1 or parents[0] in chain:
                return []
            chain.append(parents[0])
        chain.reverse()
        if len(chain) == 2:
            children = self._relatives(
                chain[-1], children=True, type="joint", fullPath=True
            )
            if len(children) == 1:
                chain.append(children[0])
        return chain if len(chain) >= 3 else []

    def _pole_controller(self, handle):
        constraints = self._constraints_on(handle, ("poleVectorConstraint",))
        if len(constraints) > 1:
            self._ambiguous("Pole Vector Constraint", constraints)
        if not constraints:
            return ""
        targets = self._constraint_controller_targets(constraints[0])
        return self._unique_exact(targets, "Pole Controller")

    def _constraint_controller_targets(self, constraint):
        """Return only movable DAG targets, never the constraint node itself."""
        targets = [
            target for target in self._constraint_targets(constraint)
            if self._is_controller_node(target)
        ]
        if targets:
            return self._long_names(self._unique_nodes(targets))

        # Some custom/legacy constraints do not answer targetList reliably.
        # Inputs to the constraint are the only safe fallback; outputs lead to
        # the constrained IK handle and must not be treated as controllers.
        inputs = self._connections(
            constraint, source=True, destination=False
        )
        return self._long_names(self._unique_nodes(
            node for node in inputs
            if not self._same_node(node, constraint) and self._is_controller_node(node)
        ))

    def _is_controller_node(self, node):
        return self._node_type(node) in self.CONTROLLER_TYPES

    def _ik_controller(self, handle, selected, pole):
        constraints = self._constraints_on(
            handle, ("pointConstraint", "parentConstraint", "orientConstraint")
        )
        targets = []
        for constraint in constraints:
            targets.extend(self._constraint_targets(constraint))
        targets = self._unique_nodes(node for node in targets if node != pole)
        selected_names = {selected, self._leaf(selected)}
        direct = [
            node for node in targets
            if node in selected_names or self._leaf(node) in selected_names
        ]
        if direct:
            return self._unique_exact(direct, "IK End Controller")
        return self._unique_scored(targets, "IK End Controller", [selected, handle])

    def _fk_chain(self, selected, ik_joints):
        mappings = {}
        for constraint_type in self.FK_CONSTRAINT_TYPES:
            for constraint in self._ls(type=constraint_type):
                driven = self._constraint_driven_joint(constraint)
                targets = [
                    node for node in self._constraint_targets(constraint)
                    if self._node_type(node) in {"transform", "joint"}
                ]
                if driven and len(targets) == 1:
                    mappings[driven] = targets[0]
        connected = self._fk_chain_from_ik_connections(ik_joints, mappings)
        if connected:
            return connected

        chains = self._mapped_joint_chains(mappings, len(self._three(ik_joints)))
        if not chains:
            return [], [], []
        scores = []
        context = [selected] + list(ik_joints)
        for chain in chains:
            controls = [mappings[node] for node in chain]
            score = sum(self.context_scorer(node, context) for node in chain + controls)
            scores.append((score, chain, controls))
        best_score = max(score for score, _chain, _controls in scores)
        best = [(chain, controls) for score, chain, controls in scores if score == best_score]
        if len(best) > 1:
            self._ambiguous("FK Constraint Chain", [chain[0] for chain, _ in best])
        chain, controls = best[0]
        return chain, controls, []

    def _fk_chain_from_ik_connections(self, ik_joints, controller_mappings):
        """Resolve the three FK pairs through the blend constraints used by IK."""
        resolved = []
        all_constraints = []
        for constraint_type in self.FK_CONSTRAINT_TYPES:
            all_constraints.extend(self._ls(type=constraint_type))
        all_constraints = self._long_names(self._unique_nodes(all_constraints))

        for ik_joint in self._three(ik_joints):
            candidates = []
            for constraint in all_constraints:
                targets = self._constraint_targets(constraint)
                if not any(self._same_node(target, ik_joint) for target in targets):
                    continue
                driven = self._constraint_driven_joint(constraint)
                if not driven:
                    continue
                other_targets = [
                    target for target in targets
                    if not self._same_node(target, ik_joint)
                ]
                controls = []
                fk_joints = []
                for target in other_targets:
                    if target in controller_mappings:
                        fk_joints.append(target)
                        controls.append(controller_mappings[target])
                    elif self._node_type(target) in self.CONTROLLER_TYPES:
                        # Some external rigs use joint nodes directly as their
                        # animator-facing FK controls (Diana-style). The blend
                        # constraint itself is the evidence that the target is
                        # the corresponding FK driver; do not require a name.
                        fk_joints.append(
                            target if self._node_type(target) == "joint" else driven
                        )
                        controls.append(target)
                pairs = self._unique_nodes(
                    f"{joint}\0{control}" for joint, control in zip(fk_joints, controls)
                )
                candidates.extend(
                    (pair.split("\0", 1)[0], pair.split("\0", 1)[1], driven)
                    for pair in pairs
                )
            candidates = list(dict.fromkeys(candidates))
            # A single FK/IK end driver may feed both a twist/roll joint and
            # the actual limb end. When the controller pair is identical,
            # hierarchy provides safe evidence: use the unique deepest driven
            # joint only when every other candidate is its ancestor.
            pairs = {(joint, control) for joint, control, _driven in candidates}
            if len(candidates) > 1 and len(pairs) == 1:
                deepest = max(candidates, key=lambda item: str(item[2]).count("|"))
                deepest_path = str(deepest[2])
                if all(
                    deepest_path == str(candidate[2]) or
                    deepest_path.startswith(str(candidate[2]).rstrip("|") + "|")
                    for candidate in candidates
                ):
                    candidates = [deepest]
            if len(candidates) > 1:
                listing = [f"{joint} <- {control}" for joint, control, _ in candidates]
                self._ambiguous("FK/IK Constraint Pair", listing)
            if not candidates:
                return None
            resolved.append(candidates[0])

        fk_joints = [joint for joint, _control, _deform in resolved]
        controls = [control for _joint, control, _deform in resolved]
        deform = [deform for _joint, _control, deform in resolved]
        if len(set(fk_joints)) != 3 or len(set(controls)) != 3 or len(set(deform)) != 3:
            return None
        return fk_joints, controls, deform

    def _mapped_joint_chains(self, mappings, chain_length=3):
        nodes = set(mappings)
        roots = []
        for node in nodes:
            parents = self._relatives(node, parent=True, type="joint", fullPath=True)
            if not any(parent in nodes for parent in parents):
                roots.append(node)
        chains = []
        for root in roots:
            chain = [root]
            while True:
                children = [
                    child for child in self._relatives(
                        chain[-1], children=True, type="joint", fullPath=True
                    ) if child in nodes
                ]
                if len(children) != 1:
                    break
                chain.append(children[0])
            if len(chain) >= chain_length:
                chains.extend(
                    chain[index:index + chain_length]
                    for index in range(len(chain) - chain_length + 1)
                )
        return chains

    def _deform_chain(self, ik_joints, fk_joints):
        result = []
        for ik_joint, fk_joint in zip(self._three(ik_joints), self._three(fk_joints)):
            candidates = []
            for constraint_type in self.FK_CONSTRAINT_TYPES:
                for constraint in self._connections(
                    ik_joint, source=False, destination=True, type=constraint_type
                ):
                    targets = self._constraint_targets(constraint)
                    if fk_joint not in targets or ik_joint not in targets:
                        continue
                    driven = self._constraint_driven_joint(constraint)
                    if driven:
                        candidates.append(driven)
            candidates = self._unique_nodes(candidates)
            if len(candidates) != 1:
                return []
            result.append(candidates[0])
        return result if len(set(result)) == 3 else []

    def _shared_switch(self, controls, extra_nodes):
        reach = defaultdict(set)
        controls = self._unique_nodes(controls)
        seeds = self._unique_nodes(controls + extra_nodes)
        for seed in seeds:
            search_items = [seed]
            if seed in controls:
                search_items = [f"{node}.visibility" for node in self._dag_lineage(seed, 3)]
            plugs = set()
            for item in search_items:
                plugs.update(self._upstream_user_plugs(item, maximum_depth=5))
            for plug in plugs:
                reach[plug].add(seed)
        if not reach:
            return ""
        best_count = max(map(len, reach.values()))
        if best_count < 2:
            return ""
        best = sorted(plug for plug, affected in reach.items() if len(affected) == best_count)
        if len(best) > 1:
            self._ambiguous("FKIK Switch", best)
        return best[0]

    def _dag_lineage(self, node, maximum_depth):
        result = [node]
        current = node
        for _index in range(maximum_depth):
            parents = self._relatives(current, parent=True, fullPath=True)
            if len(parents) != 1:
                break
            current = parents[0]
            result.append(current)
        return result

    def _upstream_user_plugs(self, start, maximum_depth):
        found = set()
        queue = deque([(start, 0)])
        visited = {start}
        while queue:
            item, depth = queue.popleft()
            if depth >= maximum_depth:
                continue
            plugs = self._connections(
                item, source=True, destination=False, plugs=True
            )
            for plug in plugs:
                node, _, attr = str(plug).partition(".")
                if not attr:
                    continue
                if self._node_type(node) in {"transform", "joint"}:
                    user_attrs = set(self._list_attr(node, userDefined=True))
                    if attr.split("[", 1)[0] in user_attrs:
                        found.add(f"{node}.{attr}")
                if node not in visited:
                    visited.add(node)
                    queue.append((node, depth + 1))
        return found

    def _constraints_for_nodes(self, nodes):
        result = []
        for node in nodes:
            for constraint_type in self.CONSTRAINT_TYPES:
                result.extend(self._connections(node, type=constraint_type))
        return self._long_names(self._unique_nodes(result))

    def _constraints_on(self, node, types):
        candidates = []
        children = self._relatives(node, children=True, fullPath=True)
        connected = self._connections(node, source=True, destination=True)
        for item in children + connected:
            if self._node_type(item) in types:
                candidates.append(item)
        return self._long_names(self._unique_nodes(candidates))

    def _constraint_targets(self, constraint):
        constraint_type = self._node_type(constraint)
        try:
            command = getattr(self.cmds, constraint_type)
            targets = command(constraint, query=True, targetList=True) or []
        except (AttributeError, TypeError, RuntimeError):
            return []
        return self._long_names(targets)

    def _constraint_driven_joint(self, constraint):
        parents = self._relatives(constraint, parent=True, type="joint", fullPath=True)
        if len(parents) == 1:
            return parents[0]
        outputs = self._connections(
            constraint, source=False, destination=True, type="joint"
        )
        return outputs[0] if len(outputs) == 1 else ""

    def _graph_distances(self, start, maximum_depth):
        distances = {start: 0}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            depth = distances[node]
            if depth >= maximum_depth:
                continue
            neighbors = self._connections(node, source=True, destination=True)
            neighbors += self._relatives(node, parent=True, fullPath=True)
            neighbors += self._relatives(node, children=True, fullPath=True)
            for neighbor in self._unique_nodes(neighbors):
                if neighbor not in distances:
                    distances[neighbor] = depth + 1
                    queue.append(neighbor)
        return distances

    def _unique_scored(self, candidates, role, context):
        candidates = self._long_names(self._unique_nodes(candidates))
        if len(candidates) < 2:
            return candidates[0] if candidates else ""
        scores = [(self.context_scorer(node, context), node) for node in candidates]
        best_score = max(score for score, _node in scores)
        best = [node for score, node in scores if score == best_score]
        if len(best) > 1:
            self._ambiguous(role, best)
        return best[0]

    def _unique_exact(self, candidates, role):
        candidates = self._long_names(self._unique_nodes(candidates))
        if len(candidates) > 1:
            self._ambiguous(role, candidates)
        return candidates[0] if candidates else ""

    @staticmethod
    def _three(chain):
        return [chain[0], chain[len(chain) // 2], chain[-1]]

    @staticmethod
    def _unique_nodes(nodes):
        return list(dict.fromkeys(str(node) for node in nodes if node))

    def _long_names(self, nodes):
        result = []
        for node in nodes:
            matches = self._ls(node, long=True)
            result.append(matches[0] if len(matches) == 1 else str(node))
        return self._unique_nodes(result)

    def _node_type(self, node):
        try:
            return self.cmds.nodeType(node)
        except (AttributeError, TypeError, RuntimeError):
            return ""

    def _connections(self, node, **kwargs):
        try:
            return list(self.cmds.listConnections(node, **kwargs) or [])
        except (AttributeError, TypeError, RuntimeError):
            return []

    def _relatives(self, node, **kwargs):
        try:
            return list(self.cmds.listRelatives(node, **kwargs) or [])
        except (AttributeError, TypeError, RuntimeError):
            return []

    def _list_attr(self, node, **kwargs):
        try:
            return list(self.cmds.listAttr(node, **kwargs) or [])
        except (AttributeError, TypeError, RuntimeError):
            return []

    def _ls(self, *args, **kwargs):
        try:
            return list(self.cmds.ls(*args, **kwargs) or [])
        except (AttributeError, TypeError, RuntimeError):
            return []

    def _log(self, message):
        self.debug_log.append(str(message))

    @staticmethod
    def _three_or_empty(nodes):
        values = list(nodes[:3])
        return values if len(values) == 3 else ["", "", ""]

    @staticmethod
    def _leaf(node):
        return str(node).rsplit("|", 1)[-1]

    @classmethod
    def _same_node(cls, left, right):
        return str(left) == str(right) or cls._leaf(left) == cls._leaf(right)

    @staticmethod
    def _ambiguous(role, candidates):
        listing = "\n".join(f"- {candidate}" for candidate in candidates)
        raise ValueError(f"{role}を一意に解決できません。\n\nCandidates:\n{listing}")
