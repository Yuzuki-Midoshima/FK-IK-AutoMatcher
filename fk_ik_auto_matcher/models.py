"""Serializable matcher settings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path


@dataclass(slots=True)
class MatchSettings:
    start_joint: str = ""
    middle_joint: str = ""
    end_joint: str = ""
    ik_controller: str = ""
    pole_controller: str = ""
    switch_controller: str = ""
    fk_controllers: list[str] = field(default_factory=lambda: ["", "", ""])
    ik_joints: list[str] = field(default_factory=lambda: ["", "", ""])
    switch_attribute: str = "FKIK"
    fk_value: float = 0.0
    ik_value: float = 1.0
    pole_distance: float = 5.0
    pole_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    source: str = "manual"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "MatchSettings":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("設定JSONのルートはオブジェクトである必要があります。")
        data["pole_offset"] = tuple(data.get("pole_offset", (0.0, 0.0, 0.0)))
        if len(data["pole_offset"]) != 3:
            raise ValueError("pole_offsetにはX、Y、Zの3要素が必要です。")
        return cls(**data)

    @property
    def deform_joints(self) -> list[str]:
        return [self.start_joint, self.middle_joint, self.end_joint]

    @property
    def switch_plug(self) -> str:
        if not self.switch_controller or not self.switch_attribute:
            return ""
        return f"{self.switch_controller}.{self.switch_attribute}"
