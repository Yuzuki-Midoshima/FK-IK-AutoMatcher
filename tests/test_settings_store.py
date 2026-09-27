import tempfile
from pathlib import Path
import unittest

from fk_ik_auto_matcher.models import MatchSettings
from fk_ik_auto_matcher.settings_store import MatchSettingsStore


class MatchSettingsStoreTests(unittest.TestCase):
    def test_default_store_is_inside_package(self):
        store = MatchSettingsStore()
        self.assertEqual(store.path.name, "match_settings.json")
        self.assertEqual(store.directory.name, "match_settings")
        self.assertEqual(store.directory.parent.name, "fk_ik_auto_matcher")

    def test_save_and_load_use_dedicated_path(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "dedicated.json"
            store = MatchSettingsStore(Path(root) / "settings")
            expected = MatchSettings(
                start_joint="start",
                fk_controllers=["fk1", "fk2", "fk3"],
            )

            saved_path = store.save(expected, path)
            actual = store.load(path)

        self.assertEqual(saved_path, path)
        self.assertEqual(actual, expected)

    def test_load_reports_missing_dedicated_file(self):
        with tempfile.TemporaryDirectory() as root:
            store = MatchSettingsStore(Path(root) / "settings")
            with self.assertRaisesRegex(ValueError, "保存済みの設定がありません"):
                store.load(Path(root) / "missing.json")

    def test_legacy_file_is_copied_into_settings_folder(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            legacy = root_path / "legacy.json"
            legacy.write_text(MatchSettings(start_joint="legacy").to_json(), encoding="utf-8")
            store = MatchSettingsStore(root_path / "settings")
            store.legacy_path = legacy

            directory = store.prepare_directory()

            self.assertEqual(directory, root_path / "settings")
            self.assertEqual(store.load().start_joint, "legacy")


if __name__ == "__main__":
    unittest.main()
