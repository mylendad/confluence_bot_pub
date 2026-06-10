from services.bot.http_adapter import SyncLastEventsResponse, SyncStatusResponse
from shared.factory import build_metadata_repository, build_state_repository


class SyncStatusService:
    def get_last_events(self) -> SyncLastEventsResponse:
        s_repo = build_state_repository()
        m_repo = build_metadata_repository()
        states = s_repo.list_all()
        dms = m_repo.list_datamarts()
        
        lp = max([s.last_synced_at for s in states if s.last_synced_at]).isoformat() if states and any(s.last_synced_at for s in states) else None
        lru = max([d.get("updated_at") for d in dms if d.get("updated_at")]) if dms else None
        
        return SyncLastEventsResponse(last_parsing=lp, last_rag_update=lru, status="ok")

    def get_status(self) -> SyncStatusResponse:
        repo = build_state_repository()
        states = repo.list_all()
        if not states:
            return SyncStatusResponse(last_sync=None, total_datamarts=0, status="no_data", resources=[])
        
        ls = max([s.last_synced_at for s in states if s.last_synced_at]).isoformat() if any(s.last_synced_at for s in states) else None
        res = [
            {
                "datamart": s.datamart_name,
                "file": s.file_name,
                "last_synced": s.last_synced_at.isoformat() if s.last_synced_at else None,
                "status": "synced" if s.content_hash else "pending",
            }
            for s in states
        ]
        return SyncStatusResponse(
            last_sync=ls,
            total_datamarts=len(set(s.datamart_name for s in states)),
            status="ok",
            resources=res,
        )
