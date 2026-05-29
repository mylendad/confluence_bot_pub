from dataclasses import dataclass

from app.storage.s2t_state_repository import S2TState


@dataclass(frozen=True)
class MetadataDecision:
    changed: bool
    reasons: list[str]


class StateComparator:
    def compare(
        self, previous: S2TState | None, metadata_hash: str, metadata: dict
    ) -> MetadataDecision:
        if previous is None:
            return MetadataDecision(changed=True, reasons=["new resource"])
        if previous.metadata_hash == metadata_hash:
            return MetadataDecision(changed=False, reasons=["metadata unchanged"])

        reasons = []
        old_metadata = previous.metadata or {}
        
        # Сначала проверяем на полное соответствие контента
        if old_metadata == metadata:
            return MetadataDecision(changed=False, reasons=["metadata hash changed but content same"])

        # Если контент разный, собираем причины для отладки
        for key, value in metadata.items():
            if old_metadata.get(key) != value:
                reasons.append(f"{key}: {old_metadata.get(key)!r} -> {value!r}")
        
        # Проверяем, не удалены ли ключи
        for key in old_metadata:
            if key not in metadata:
                reasons.append(f"removed key: {key}")

        return MetadataDecision(changed=True, reasons=reasons or ["metadata hash changed"])
