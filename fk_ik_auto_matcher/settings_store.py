"""Tool-local persistence for manual FK/IK match settings."""

from __future__ import annotations

from pathlib import Path
import shutil

from .models import MatchSettings


class MatchSettingsStore:
    """Read and write JSON files in the tool's dedicated settings folder."""

    def __init__(self, directory: str | Path | None = None):
        self.directory = (
            Path(directory) if directory else Path(__file__).with_name("match_settings")
        )
        self.path = self.directory / "match_settings.json"
        self.legacy_path = Path(__file__).with_name("match_settings.json")

    def prepare_directory(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.legacy_path.is_file() and not self.path.exists():
            shutil.copy2(self.legacy_path, self.path)
        return self.directory

    def save(self, settings: MatchSettings, path: str | Path | None = None) -> Path:
        self.prepare_directory()
        destination = Path(path) if path else self.path
        settings.save(destination)
        return destination

    def load(self, path: str | Path | None = None) -> MatchSettings:
        self.prepare_directory()
        source = Path(path) if path else self.path
        if not source.is_file():
            raise ValueError(f"保存済みの設定がありません: {source}")
        return MatchSettings.load(source)
