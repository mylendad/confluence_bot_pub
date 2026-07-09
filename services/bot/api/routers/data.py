import re
from fastapi import APIRouter

from shared.factory import build_metadata_repository
from shared.utils.text_utils import normalize_text

router = APIRouter(tags=["Data"])

@router.get("/api/datamarts/list", response_model=list[str], summary="Список витрин")
async def list_datamarts():
    meta_repo = build_metadata_repository()
    datamarts = meta_repo.list_datamarts()
    
    # Фильтрация технических страниц
    junk = r"\bтз\b|техническ[ои][еи] задани[ея]|чек лист|препятствия|функциональное решение|функцональное решение|страниц[аы] для 2лс|копия|изменения в релизах"
    
    filtered = []
    for dm in datamarts:
        name = dm.get("name", "")
        if not name:
            continue
        if "inner" in name.lower():
            filtered.append(name)
            continue
        if re.search(junk, normalize_text(name), re.IGNORECASE):
            continue
        if re.search(r"тз\s*-|тз\s*--", name.lower()):
            continue
        filtered.append(name)
        
    return sorted(set(filtered))
