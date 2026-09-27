"""Compact standalone PySide6 interface."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from .matcher import MatchService
from .models import MatchSettings
from .resolver import RigResolver
from .settings_store import MatchSettingsStore


class MainWindow(QtWidgets.QDialog):
    def __init__(self, parent=None, cmds_module=None):
        super().__init__(parent)
        self.setObjectName("FKIKAutoMatcherWindow")
        self.setWindowTitle("FK-IK AutoMatcher 1.0.0")
        self.resize(590, 470)
        self.setMinimumSize(590, 470)
        self.setSizeGripEnabled(True)
        self.cmds = cmds_module
        if self.cmds is None:
            import maya.cmds as cmds_module
            self.cmds = cmds_module
        self.resolver = RigResolver(self.cmds)
        self.matcher = MatchService(self.cmds)
        self.settings_store = MatchSettingsStore()
        self._selection_job = None
        self._switch_job = None
        self._build_ui()
        self._install_selection_callback()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(8)
        auto = QtWidgets.QGroupBox("1. 自動設定")
        auto.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        auto_layout = QtWidgets.QGridLayout(auto)
        self.reference = QtWidgets.QLineEdit()
        self.reference.setPlaceholderText("FKIK内のノードを選択")
        get_selected = QtWidgets.QPushButton("選択を設定")
        detect = QtWidgets.QPushButton("リグを自動解析")
        get_selected.clicked.connect(self._get_reference)
        detect.clicked.connect(self._detect)
        auto_layout.addWidget(QtWidgets.QLabel("基準ノード"), 0, 0)
        auto_layout.addWidget(self.reference, 0, 1)
        auto_layout.addWidget(get_selected, 0, 2)
        auto_layout.addWidget(detect, 1, 0, 1, 3)
        self.status = QtWidgets.QPlainTextEdit("未解析")
        self.status.setReadOnly(True)
        self.status.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.status.setMinimumHeight(120)
        self.status.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.status.setStyleSheet("padding:5px; background:#333; border:1px solid #555;")
        auto_layout.addWidget(self.status, 2, 0, 1, 3)

        details = QtWidgets.QGroupBox("2. 解析結果・詳細設定")
        details.setCheckable(True)
        details.setChecked(False)
        details_layout = QtWidgets.QVBoxLayout(details)
        details_layout.setContentsMargins(6, 6, 6, 6)
        details_scroll = QtWidgets.QScrollArea()
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        details_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        details_scroll.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        details_scroll.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
        )
        details_scroll.setMinimumHeight(160)
        details_content = QtWidgets.QWidget()
        form = QtWidgets.QGridLayout(details_content)
        form.setContentsMargins(4, 4, 4, 4)
        details_scroll.setWidget(details_content)
        details_layout.addWidget(details_scroll)
        self.details_scroll = details_scroll
        definitions = (
            ("start_joint", "Deform 始点"), ("middle_joint", "Deform 中間"),
            ("end_joint", "Deform 終点"), ("ik_controller", "IK Controller"),
            ("pole_controller", "Pole Controller"),
            ("switch_controller", "Switch Controller"),
            ("fk_0", "FK 始点"), ("fk_1", "FK 中間"), ("fk_2", "FK 終点"),
            ("ik_0", "IK Joint 始点"), ("ik_1", "IK Joint 中間"),
            ("ik_2", "IK Joint 終点"),
        )
        self.edits = {}
        for row, (key, label) in enumerate(definitions):
            edit = QtWidgets.QLineEdit()
            button = QtWidgets.QPushButton("選択")
            button.clicked.connect(lambda _=False, target=edit: self._set_selected(target))
            form.addWidget(QtWidgets.QLabel(label), row, 0)
            form.addWidget(edit, row, 1)
            form.addWidget(button, row, 2)
            self.edits[key] = edit
        self.switch_attribute = QtWidgets.QLineEdit("FKIK")
        setting_row = len(definitions)
        form.addWidget(QtWidgets.QLabel("切替属性"), setting_row, 0)
        form.addWidget(self.switch_attribute, setting_row, 1)
        self.fk_value = QtWidgets.QDoubleSpinBox()
        self.fk_value.setRange(-99999.0, 99999.0)
        self.fk_value.setValue(0.0)
        form.addWidget(QtWidgets.QLabel("FK Value"), setting_row + 1, 0)
        form.addWidget(self.fk_value, setting_row + 1, 1)
        self.ik_value = QtWidgets.QDoubleSpinBox()
        self.ik_value.setRange(-99999.0, 99999.0)
        self.ik_value.setValue(1.0)
        form.addWidget(QtWidgets.QLabel("IK Value"), setting_row + 2, 0)
        form.addWidget(self.ik_value, setting_row + 2, 1)
        self.pole_distance = QtWidgets.QDoubleSpinBox()
        self.pole_distance.setRange(-99999.0, 99999.0)
        self.pole_distance.setValue(5.0)
        form.addWidget(QtWidgets.QLabel("Pole距離"), setting_row + 3, 0)
        form.addWidget(self.pole_distance, setting_row + 3, 1)
        self.pole_offsets = []
        offset_host = QtWidgets.QWidget()
        offset_layout = QtWidgets.QHBoxLayout(offset_host)
        offset_layout.setContentsMargins(0, 0, 0, 0)
        for axis in "XYZ":
            box = QtWidgets.QDoubleSpinBox()
            box.setRange(-99999.0, 99999.0)
            self.pole_offsets.append(box)
            offset_layout.addWidget(QtWidgets.QLabel(axis))
            offset_layout.addWidget(box, 1)
        form.addWidget(QtWidgets.QLabel("Poleオフセット"), setting_row + 4, 0)
        form.addWidget(offset_host, setting_row + 4, 1)
        details.setMaximumHeight(24)
        details.toggled.connect(lambda checked: self._toggle_details(details, checked))

        content_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        content_splitter.setChildrenCollapsible(False)
        content_splitter.setHandleWidth(7)
        content_splitter.addWidget(auto)
        content_splitter.addWidget(details)
        content_splitter.setStretchFactor(0, 1)
        content_splitter.setStretchFactor(1, 2)
        content_splitter.setSizes([260, 24])
        layout.addWidget(content_splitter, 1)
        self.content_splitter = content_splitter

        actions = QtWidgets.QGroupBox("3. マッチ実行")
        actions.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Maximum,
        )
        actions_layout = QtWidgets.QGridLayout(actions)
        actions_layout.setContentsMargins(10, 8, 10, 10)
        actions_layout.setVerticalSpacing(0)
        self.fk_to_ik_button = QtWidgets.QPushButton("FK  →  IK")
        self.ik_to_fk_button = QtWidgets.QPushButton("IK  →  FK")
        for button in (self.fk_to_ik_button, self.ik_to_fk_button):
            button.setMinimumHeight(62)
            font = button.font()
            font.setPointSize(11)
            font.setWeight(QtGui.QFont.Weight.DemiBold)
            button.setFont(font)
        validate = QtWidgets.QPushButton("設定を検証")
        save = QtWidgets.QPushButton("JSON保存")
        load = QtWidgets.QPushButton("JSON読込")
        self.fk_to_ik_button.clicked.connect(lambda: self._match("fk_to_ik"))
        self.ik_to_fk_button.clicked.connect(lambda: self._match("ik_to_fk"))
        validate.clicked.connect(self._validate)
        save.clicked.connect(self._save)
        load.clicked.connect(self._load)
        match_layout = QtWidgets.QHBoxLayout()
        match_layout.setSpacing(8)
        match_layout.addWidget(self.fk_to_ik_button, 1)
        match_layout.addWidget(self.ik_to_fk_button, 1)
        actions_layout.addLayout(match_layout, 0, 0, 1, 3)
        actions_layout.setRowMinimumHeight(1, 22)
        actions_layout.addWidget(validate, 2, 0)
        actions_layout.addWidget(save, 2, 1)
        actions_layout.addWidget(load, 2, 2)
        layout.addWidget(actions, 0)
        self._set_action_state()

    def _toggle_details(self, details, checked):
        """Let details use available height while keeping actions visible."""
        details.setMaximumHeight(16777215 if checked else 24)
        details.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            (QtWidgets.QSizePolicy.Policy.Expanding if checked else
             QtWidgets.QSizePolicy.Policy.Fixed),
        )
        self.details_scroll.setVisible(checked)
        if checked:
            available = max(self.content_splitter.height(), 360)
            self.content_splitter.setSizes([
                max(150, available // 3),
                max(210, available * 2 // 3),
            ])
        else:
            self.content_splitter.setSizes([
                max(self.content_splitter.height() - 24, 200), 24
            ])
        self.layout().invalidate()

    def _get_reference(self):
        selected = self.cmds.ls(selection=True, long=True) or []
        if selected:
            self.reference.setText(selected[0])
            self.status.setPlainText("未解析")
            self.status.setStyleSheet(
                "padding:5px; background:#333; border:1px solid #555;"
            )

    def _set_selected(self, edit):
        selected = self.cmds.ls(selection=True, long=True) or []
        if selected:
            edit.setText(selected[0])

    def _detect(self):
        try:
            settings = self.resolver.resolve(self.reference.text().strip())
            self._show_settings(settings)
            self.status.setPlainText(self._resolution_report(settings))
            self.status.setStyleSheet("padding:5px; background:#29443d; border:1px solid #3c8878;")
        except Exception as error:
            self.status.setPlainText("解析失敗: " + str(error))
            self.status.setStyleSheet("padding:5px; background:#4a3434; border:1px solid #8b5555;")

    @staticmethod
    def _resolution_report(settings):
        lines = ["解析完了: " + settings.source]
        entries = [
            ("IK End Controller", settings.ik_controller, "ik_controller"),
            ("Pole Controller", settings.pole_controller, "pole_controller"),
        ]
        positions = ("Start", "Mid", "End")
        entries.extend(
            (f"FK {position} Controller", node, "fk_controllers")
            for position, node in zip(positions, settings.fk_controllers)
        )
        entries.extend(
            (f"FK {position} Joint", node, "fk_joints")
            for position, node in zip(positions, settings.fk_joints)
            if node
        )
        entries.extend(
            (f"IK {position} Joint", node, "ik_joints")
            for position, node in zip(positions, settings.ik_joints)
        )
        entries.append(("FKIK Switch", settings.switch_plug, "switch_plug"))
        for label, value, key in entries:
            method = settings.resolution_methods.get(key)
            if not method or not value:
                continue
            confidence = settings.resolution_confidence.get(key, "")
            suffix = f" (Confidence: {confidence})" if confidence else ""
            lines.extend((label, value, f"Resolved by: {method}{suffix}"))
        if settings.resolution_errors:
            lines.append("\n未解決項目:")
            lines.extend(
                f"- {key}: {message}"
                for key, message in sorted(settings.resolution_errors.items())
            )
        if settings.debug_log:
            lines.append("\nDebug Log:")
            lines.extend(settings.debug_log)
        return "\n".join(lines)

    def _settings(self):
        return MatchSettings(
            start_joint=self.edits["start_joint"].text().strip(),
            middle_joint=self.edits["middle_joint"].text().strip(),
            end_joint=self.edits["end_joint"].text().strip(),
            ik_controller=self.edits["ik_controller"].text().strip(),
            pole_controller=self.edits["pole_controller"].text().strip(),
            switch_controller=self.edits["switch_controller"].text().strip(),
            fk_controllers=[self.edits[f"fk_{i}"].text().strip() for i in range(3)],
            ik_joints=[self.edits[f"ik_{i}"].text().strip() for i in range(3)],
            switch_attribute=self.switch_attribute.text().strip() or "FKIK",
            fk_value=self.fk_value.value(),
            ik_value=self.ik_value.value(),
            pole_distance=self.pole_distance.value(),
            pole_offset=tuple(box.value() for box in self.pole_offsets),
        )

    def _show_settings(self, settings):
        for key in ("start_joint", "middle_joint", "end_joint", "ik_controller",
                    "pole_controller", "switch_controller"):
            self.edits[key].setText(getattr(settings, key))
        for index, value in enumerate(settings.fk_controllers):
            self.edits[f"fk_{index}"].setText(value)
        for index, value in enumerate(settings.ik_joints):
            self.edits[f"ik_{index}"].setText(value)
        self.switch_attribute.setText(settings.switch_attribute)
        self.fk_value.setValue(settings.fk_value)
        self.ik_value.setValue(settings.ik_value)
        self.pole_distance.setValue(settings.pole_distance)
        for box, value in zip(self.pole_offsets, settings.pole_offset):
            box.setValue(value)
        self._install_switch_callback(settings)
        self._set_action_state(settings)

    def _set_action_state(self, settings=None):
        """Highlight the direction matching the selected controller or rig state."""
        available_style = (
            "QPushButton { background-color: #526873; color: #ffffff; "
            "border: none; border-radius: 4px; padding: 8px; } "
            "QPushButton:hover { background-color: #607985; } "
            "QPushButton:pressed { background-color: #465a64; }"
        )
        unavailable_style = (
            "QPushButton:disabled { background-color: #353535; color: #777777; "
            "border: 1px solid #454545; border-radius: 4px; padding: 8px; }"
        )
        enabled = {"fk_to_ik": True, "ik_to_fk": True}
        state_was_read = False
        if settings and settings.switch_plug and self.cmds.objExists(settings.switch_plug):
            try:
                value = float(self.cmds.getAttr(settings.switch_plug))
                fk_delta = abs(value - settings.fk_value)
                ik_delta = abs(value - settings.ik_value)
                if fk_delta < ik_delta:
                    enabled["ik_to_fk"] = False
                elif ik_delta < fk_delta:
                    enabled["fk_to_ik"] = False
                state_was_read = True
            except (TypeError, ValueError, RuntimeError):
                pass
        if not state_was_read and settings:
            selected_direction = self._direction_from_selection(settings)
            if selected_direction:
                enabled = {
                    "fk_to_ik": selected_direction == "fk_to_ik",
                    "ik_to_fk": selected_direction == "ik_to_fk",
                }
        for direction, button in (
            ("fk_to_ik", self.fk_to_ik_button),
            ("ik_to_fk", self.ik_to_fk_button),
        ):
            button.setEnabled(enabled[direction])
            button.setStyleSheet(available_style if enabled[direction] else unavailable_style)

    def _direction_from_selection(self, settings):
        selected = self.cmds.ls(selection=True, long=True) or []
        if not selected:
            return None
        selected_names = {selected[0], selected[0].rsplit("|", 1)[-1]}

        def contains(nodes):
            return any(
                node and ({node, node.rsplit("|", 1)[-1]} & selected_names)
                for node in nodes
            )

        if contains(settings.fk_controllers):
            return "fk_to_ik"
        if contains([settings.ik_controller, settings.pole_controller]):
            return "ik_to_fk"
        return None

    def _install_selection_callback(self):
        try:
            self._selection_job = self.cmds.scriptJob(
                event=["SelectionChanged", self._selection_changed],
                protected=True,
            )
        except (AttributeError, RuntimeError):
            self._selection_job = None

    def _install_switch_callback(self, settings):
        self._kill_script_job("_switch_job")
        if not settings.switch_plug or not self.cmds.objExists(settings.switch_plug):
            return
        try:
            self._switch_job = self.cmds.scriptJob(
                attributeChange=[settings.switch_plug, self._rig_state_changed],
                protected=True,
            )
        except (AttributeError, RuntimeError):
            self._switch_job = None

    def _rig_state_changed(self):
        self._set_action_state(self._settings())

    def _selection_changed(self):
        self._set_action_state(self._settings())

    def _kill_script_job(self, attribute):
        job = getattr(self, attribute, None)
        if job:
            try:
                if self.cmds.scriptJob(exists=job):
                    self.cmds.scriptJob(kill=job, force=True)
            except (AttributeError, RuntimeError):
                pass
        setattr(self, attribute, None)

    def closeEvent(self, event):
        self._kill_script_job("_selection_job")
        self._kill_script_job("_switch_job")
        super().closeEvent(event)

    def _match(self, direction):
        try:
            settings = self._settings()
            configured_nodes = (
                settings.deform_joints + settings.fk_controllers + settings.ik_joints +
                [settings.ik_controller, settings.pole_controller,
                 settings.switch_controller]
            )
            if not any(configured_nodes):
                reference = self.reference.text().strip()
                if not reference:
                    selected = self.cmds.ls(selection=True, long=True) or []
                    reference = selected[0] if selected else ""
                    if reference:
                        self.reference.setText(reference)
                settings = self.resolver.resolve(reference)
                self._show_settings(settings)
            getattr(self.matcher, direction)(settings)
            message = "マッチ完了。Maya Undoで1回で戻せます。"
            if self.matcher.last_debug_log:
                message += "\n\n" + "\n".join(self.matcher.last_debug_log)
            self.status.setPlainText(message)
            self.status.setStyleSheet(
                "padding:5px; background:#29443d; border:1px solid #3c8878;"
            )
            self._set_action_state(settings)
        except Exception as error:
            self.status.setPlainText("マッチ失敗: " + str(error))
            self.status.setStyleSheet(
                "padding:5px; background:#4a3434; border:1px solid #8b5555;"
            )

    def _validate(self):
        settings = self._settings()
        issues = sorted(set(self.matcher.validate(settings, "fk_to_ik") +
                            self.matcher.validate(settings, "ik_to_fk")))
        message = "設定に問題はありません。" if not issues else "\n".join(issues)
        QtWidgets.QMessageBox.information(self, "設定検証", message)

    def _save(self):
        try:
            self.settings_store.prepare_directory()
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "設定保存",
                str(self.settings_store.path),
                "JSON (*.json)",
            )
            if not path:
                return
            path = self.settings_store.save(self._settings(), path)
            self.status.setPlainText(f"設定を保存しました:\n{path}")
            self.status.setStyleSheet(
                "padding:5px; background:#29443d; border:1px solid #3c8878;"
            )
        except (OSError, ValueError) as error:
            self.status.setPlainText("設定保存失敗: " + str(error))
            self.status.setStyleSheet(
                "padding:5px; background:#4a3434; border:1px solid #8b5555;"
            )

    def _load(self):
        try:
            directory = self.settings_store.prepare_directory()
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "設定読込",
                str(directory),
                "JSON (*.json)",
            )
            if not path:
                return
            settings = self.settings_store.load(path)
            self._show_settings(settings)
            self.status.setPlainText(
                f"設定を読み込みました:\n{path}"
            )
            self.status.setStyleSheet(
                "padding:5px; background:#29443d; border:1px solid #3c8878;"
            )
        except (OSError, ValueError, TypeError) as error:
            self.status.setPlainText("設定読込失敗: " + str(error))
            self.status.setStyleSheet(
                "padding:5px; background:#4a3434; border:1px solid #8b5555;"
            )
