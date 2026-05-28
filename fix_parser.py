import re
from datetime import datetime

file_path = 'app/confluence/parser.py'
with open(file_path, 'r') as f:
    content = f.read()

# Расширяем логику поиска даты завершения
old_block = """            # 1. Ищем дату завершения (переход в "Сделан" или установка значения в поле типа изменения)
            tag = (change.change_type or "").lower()
            done_statuses = {
                "сделан",
                "сделано",
                "done",
                "resolved",
                "решено",
                "закрыт",
                "closed",
                "выполнено",
                "выполнен",
                "завершено",
                "завершен",
            }

            for history in histories:
                history_created = history.get("created")
                found_done_in_this_history = False
                for item in history.get("items", []):
                    field_name = (item.get("field") or "").lower()
                    status_name = (item.get("toString") or "").lower()
                    
                    # Либо это системный статус "Сделан"
                    if field_name == "status" and status_name in done_statuses:
                        found_done_in_this_history = True
                    
                    # Либо это наше поле-тег (например ИСПРАВЛЕНИЕ) получило значение "Сделан"
                    elif tag and field_name == tag and status_name in done_statuses:
                        found_done_in_this_history = True
                    
                if found_done_in_this_history:
                    try:
                        change.jira_done_at = datetime.fromisoformat(
                            history_created.replace("Z", "+00:00")
                        )
                        break
                    except Exception:
                        pass"""

new_block = """            # 1. Ищем дату завершения (поле Status или Решение)
            tag = (change.change_type or "").lower()
            done_statuses = {
                "сделан", "сделано", "done", "resolved", "решено", "закрыт", "closed",
                "выполнено", "выполнен", "завершено", "завершен", "готово", "готов"
            }

            for history in histories:
                history_created = history.get("created")
                found_done_in_this_history = False
                for item in history.get("items", []):
                    field_name = (item.get("field") or "").lower()
                    status_name = (item.get("toString") or "").lower()
                    
                    # Проверяем системные поля (Status, Resolution/Решение) или поле-тег из Confluence
                    is_done_field = field_name in {"status", "resolution", "решение"}
                    is_tag_field = tag and field_name == tag
                    
                    if (is_done_field or is_tag_field) and status_name in done_statuses:
                        found_done_in_this_history = True
                        break
                    
                if found_done_in_this_history and history_created:
                    try:
                        # Jira присылает дату типа 2025-10-15T14:04:57.000+0300
                        clean_date = history_created.replace("Z", "+00:00")
                        change.jira_done_at = datetime.fromisoformat(clean_date)
                        break
                    except Exception as exc:
                        logger.warning("Failed to parse Jira history date %s: %s", history_created, exc)"""

if old_block in content:
    new_content = content.replace(old_block, new_block)
    with open(file_path, 'w') as f:
        f.write(new_content)
    print("Successfully updated app/confluence/parser.py")
else:
    print("Could not find the target block in app/confluence/parser.py")
