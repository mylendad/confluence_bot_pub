# Incremental S2T Sync

## Цель

Инкрементальное обновление снижает нагрузку на Confluence и RAG:

- не скачивать неизмененные S2T;
- не парсить неизмененные файлы;
- не пересоздавать все RAG-документы;
- обновлять только измененные витрины.

Основная стратегия:

```text
metadata changed?
NO  -> skip download, skip parse, skip RAG update
YES -> download -> sha256(content) changed?
       NO  -> save new metadata/hash state, skip parse/RAG
       YES -> parse S2T -> diff -> partial RAG update -> save state
```

## Команды

Dry-run без фактического обновления:

```bash
.venv/bin/python -m app.cli update-rag --dry-run
```

Реальное инкрементальное обновление:

```bash
.venv/bin/python -m app.cli update-rag
```

## Шаг 1. Сбор Confluence metadata

`MetadataSyncService` вызывает `ConfluenceParser.parse(dry_run=True)` и получает список витрин
с выбранными S2T-ресурсами.

Для страницы витрины учитываются:

- `version.number`;
- `version.when`;
- `lastModified`;
- `history.lastUpdated`.

Для S2T attachment/link учитываются:

- `attachment.id`;
- `attachment.title`;
- `attachment.version.number`;
- `attachment.version.when`;
- `attachment.fileSize`;
- `downloadUrl`;
- `mediaType`;
- page/resource id;
- resource type;
- file name.

Metadata сериализуется в JSON с сортировкой ключей и хэшируется:

```text
metadata_hash = sha256(json.dumps(metadata, sort_keys=True))
```

Код:

- `app/sync/metadata_sync_service.py`
- `app/sync/hash_service.py`

## Шаг 2. Сравнение metadata

`StateComparator` сравнивает новый `metadata_hash` с сохраненным состоянием из `s2t_state`.

Решения:

| Состояние | Решение |
| --- | --- |
| Нет записи в `s2t_state` | `new resource`, скачать и проверить content hash. |
| `metadata_hash` совпал | Ничего не скачивать и не парсить. |
| `metadata_hash` изменился | Скачать файл и проверить `sha256(content)`. |

При изменении metadata comparator возвращает список причин вида:

```text
attachment_version_number: 3 -> 4
attachment_file_size: 102400 -> 103120
download_url: old -> new
```

Код:

- `app/sync/state_comparator.py`
- `app/storage/s2t_state_repository.py`

## Шаг 3. Content hash

Если metadata изменились, файл скачивается через `ConfluenceClient.download`.

После скачивания считается:

```text
content_hash = sha256(file_bytes)
```

Это финальная гарантия изменения содержимого.

Если `content_hash` совпадает с предыдущим:

- S2T не парсится;
- diff не считается;
- RAG не обновляется;
- embeddings/chunks не пересоздаются;
- новое metadata-состояние сохраняется.

Если `content_hash` изменился:

- файл сохраняется в `data/raw`;
- запускается `S2TParser`;
- рассчитывается diff;
- обновляется change log;
- обновляется только RAG по затронутой витрине;
- `s2t_state` обновляется новым `metadata_hash` и `content_hash`.

Первичная загрузка нового S2T считается baseline-синхронизацией. Если для витрины еще нет
старых атрибутов и нет сохраненного `s2t_state`, атрибуты сохраняются и индексируются, но
не записываются в `change_log` как массовые `added`. Это предотвращает шум в ответах
на вопрос "какие изменения были за последний год".

Код:

- `app/sync/incremental_updater.py`
- `app/sync/hash_service.py`

## Шаг 4. Partial RAG update

При изменении конкретной витрины вызывается:

```text
RAGIndexer.update_datamart(datamart, attributes)
```

Он выполняет:

```text
MetadataRepository.replace_attributes_for_datamart
DocumentRepository.replace_for_datamart
JsonVectorStore.replace_for_datamart
```

То есть не пересобирается весь индекс. Удаляются и создаются только документы той витрины,
S2T которой реально изменился.

Код:

- `app/rag/indexer.py`
- `app/storage/document_repository.py`
- `app/rag/vector_store.py`

## Таблица `s2t_state`

`s2t_state` хранит последнее состояние каждого S2T-ресурса:

| Поле | Назначение |
| --- | --- |
| `resource_key` | Стабильный ключ S2T-ресурса. |
| `datamart_name` | Имя витрины. |
| `metadata_json` | Последний metadata snapshot. |
| `metadata_hash` | Hash metadata snapshot. |
| `content_hash` | `sha256` последнего скачанного содержимого. |
| `last_checked_at` | Когда metadata проверялись последний раз. |
| `last_synced_at` | Когда S2T реально синхронизировался. |
| `updated_at` | Время изменения ресурса по Confluence metadata. |

## Dry-run поведение

`update-rag --dry-run`:

- получает metadata из Confluence;
- сравнивает metadata с `s2t_state`;
- показывает, что будет скачано, распарсено и переиндексировано;
- не скачивает файлы;
- не парсит S2T;
- не обновляет SQLite/RAG/change log.

Пример:

```text
Dry run S2T resources: 1
- Прокси-витрина такая-то: s2t_template_5_sheets_filled.xlsx
  metadata_changed: True
  reasons: new resource
  will_download: True
  will_parse: True
  will_reindex: True
Files to download: 1
S2T files to parse: 1
Datamarts to reindex: 1
Detected changes: 0
```

## Scheduler contract

Планировщик должен вызывать только:

```bash
.venv/bin/python -m app.cli update-rag
```

Он не должен вызывать:

```bash
.venv/bin/python -m app.cli build-rag --full
```

`build-rag --full` допустим для ручного восстановления локального индекса, но не для регулярного
обновления из Confluence.

## Failure modes

| Проблема | Поведение |
| --- | --- |
| Confluence недоступен | Команда падает с сетевой ошибкой, состояние не обновляется. |
| S2T найден, но нет download URL | Ресурс попадает в отчет, скачивание/парсинг пропускаются. |
| Metadata изменились, content hash совпал | Парсинг/RAG пропускаются, состояние metadata обновляется. |
| Content hash изменился, парсинг упал | Изменения RAG не должны считаться успешно примененными. |

## Проверки

Покрыто тестами:

- dry-run не скачивает файл;
- неизмененная metadata пропускает download/parse/RAG;
- измененная metadata с тем же content hash пропускает parse/RAG;
- owner из `UserName` парсится и доступен structured retriever.
