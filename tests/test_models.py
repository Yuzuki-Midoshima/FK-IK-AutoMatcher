import tempfile
from pathlib import Path
import unittest

from fk_ik_auto_matcher.models import MatchSettings


class MatchSettingsTests(unittest.TestCase):
    def test_json_round_trip(self):
        value = MatchSettings(
            start_joint="a", middle_joint="b", end_joint="c",
            fk_controllers=["f1", "f2", "f3"],
            ik_joints=["i1", "i2", "i3"], pole_offset=(1.0, 2.0, 3.0),
        )
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.json"
            value.save(path)
            loaded = MatchSettings.load(path)
        self.assertEqual(value, loaded)

    def test_switch_plug(self):
        value = MatchSettings(switch_controller="character:settings_CTRL")
        self.assertEqual(value.switch_plug, "character:settings_CTRL.FKIK")

    def test_empty_switch_plug(self):
        self.assertEqual(MatchSettings().switch_plug, "")

    def test_rejects_invalid_pole_offset(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.json"
            path.write_text('{"pole_offset": [1, 2]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "3要素"):
                MatchSettings.load(path)


if __name__ == "__main__":
    unittest.main()
