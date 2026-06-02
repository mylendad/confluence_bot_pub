import logging
from dataclasses import dataclass

from app.storage.s2t_state_repository import S2TState

logger = logging.getLogger(__name__)


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
            # Такое бывает если хэш-функция поменялась или в hash_metadata попали не все поля из metadata
            return MetadataDecision(changed=False, reasons=["metadata hash changed but content same"])

        # Если контент разный, собираем причины для отладки
        for key, value in metadata.items():
            old_val = old_metadata.get(key)
            if old_val != value:
                reasons.append(f"{key}: {old_val!r} -> {value!r}")
                logger.info("Metadata mismatch for '%s': key='%s' old=%r new=%r", 
                            metadata.get('datamart_name'), key, old_val, value)
        
        # Проверяем, не удалены ли ключи
        for key in old_metadata:
            if key not in metadata:
                reasons.append(f"removed key: {key}")
                logger.info("Metadata key removed for '%s': key='%s'", 
                            metadata.get('datamart_name'), key)

        return MetadataDecision(changed=True, reasons=reasons or ["metadata hash changed"])
