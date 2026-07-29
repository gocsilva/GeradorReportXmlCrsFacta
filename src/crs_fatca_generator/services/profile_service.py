from __future__ import annotations

import json
from pathlib import Path

from crs_fatca_generator.infrastructure.paths import profiles_dir
from crs_fatca_generator.models.mapping import MappingProfile


class ProfileService:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or profiles_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def list_profiles(self) -> list[Path]:
        return sorted(self.base_dir.glob("*.json"))

    def save(self, profile: MappingProfile, path: Path | None = None) -> Path:
        target = path or self.base_dir / f"{self._safe_name(profile.name)}.json"
        target.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def load(self, path: Path) -> MappingProfile:
        return MappingProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def delete(self, path: Path) -> None:
        if path.exists() and path.parent.resolve() == self.base_dir.resolve():
            path.unlink()

    def duplicate(self, source: Path, new_name: str) -> Path:
        profile = self.load(source)
        profile.name = new_name
        return self.save(profile)

    def _safe_name(self, name: str) -> str:
        return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name).strip("_") or "perfil"
