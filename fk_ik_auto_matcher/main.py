"""Maya entry point."""

from PySide6 import QtWidgets

from .ui import MainWindow


def maya_main_window():
    import maya.OpenMayaUI as omui
    from shiboken6 import wrapInstance
    pointer = omui.MQtUtil.mainWindow()
    return wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None


def show():
    app = QtWidgets.QApplication.instance()
    if app:
        for widget in app.topLevelWidgets():
            if widget.objectName() == "FKIKAutoMatcherWindow":
                widget.close()
                widget.deleteLater()
    window = MainWindow(parent=maya_main_window())
    window.show()
    window.raise_()
    window.activateWindow()
    if app:
        app._fk_ik_auto_matcher_window = window
    return window
