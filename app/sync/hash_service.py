import hashlib
import json


class HashService:
    @staticmethod
    def sha256_bytes(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def stable_metadata_hash(metadata: dict) -> str:
        payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
