# Architecture

## Назначение

Проект реализует чат-бота по витринам данных. Бот получает документацию из Confluence,
находит актуальные S2T-файлы, парсит атрибуты витрин, хранит структурированное состояние,
строит RAG-индекс и отвечает на вопросы пользователя через CLI или HTTP.

## Основные модули

| Модуль | Назначение |
| --- | --- |
| `app/confluence` | HTTP-клиент Confluence, модели страниц/ресурсов, поиск страниц витрин и S2T. |
| `app/s2t` | Парсинг Excel/CSV S2T в структурированные `S2TAttribute`. |
| `app/storage` | SQLite-репозитории для витрин, атрибутов, RAG-документов, change log и S2T sync state. |
| `app/sync` | Инкрементальное metadata-first обновление S2T и RAG. |
| `app/rag` | Построение текстовых документов, JSONL vector store, retriever, LLM adapter. |
| `app/changes` | Diff между старым и новым снимком атрибутов, запись change log. |
| `app/bot` | Бизнес-сервис и адаптеры CLI/HTTP/SberChat. |
| `app/cli.py` | CLI-команды для парсинга, обновления, вопросов и интерактивного чата. |

## Основные CLI-потоки

### Локальная загрузка S2T

```text
parse-s2t
-> S2TParser
-> MetadataRepository.upsert_datamart
-> MetadataRepository.upsert_attributes
```

Эта команда нужна для локальной разработки и smoke-тестов с файлом
`s2t_template_5_sheets_filled.xlsx`.

### Полная локальная пересборка RAG

```text
build-rag --full
-> MetadataRepository.list_attributes
-> RAGIndexer.rebuild_from_storage
-> DocumentRepository.replace_all
-> JsonVectorStore.replace_all
```

Это полный rebuild локального индекса. Для регулярного Confluence refresh должен
использоваться `update-rag`, а не `build-rag --full`.

### Инкрементальное обновление из Confluence

```text
update-rag
-> MetadataSyncService.collect
-> StateComparator.compare
-> ConfluenceClient.download only if metadata changed
-> sha256(content)
-> S2TParser only if content changed
-> DiffService.diff_attributes
-> RAGIndexer.update_datamart
-> S2TStateRepository.upsert
```

Подробности описаны в [Incremental S2T Sync](incremental-sync.md).

## Хранилища SQLite

| Таблица | Назначение |
| --- | --- |
| `datamarts` | Витрины, Confluence page id/url, stakeholders. |
| `attributes` | Распарсенные S2T-атрибуты в JSON, ключ атрибута и hash payload. |
| `documents` | Текстовые документы RAG и metadata. |
| `change_log` | История добавленных, удаленных и измененных атрибутов. |
| `s2t_state` | Последнее metadata/content состояние S2T-ресурсов для incremental sync. |

## Ключи и идентичность

### Attribute key

`S2TAttribute.attribute_key` строится из:

```text
datamart_code or datamart_name
target_schema
target_table
target_field
```

Этот ключ используется для diff и upsert атрибутов.

### S2T resource key

`S2TResource.resource_key` выбирается в порядке:

```text
id -> download_url -> url -> page_id:file_name
```

Он используется как primary key в `s2t_state`.

## Границы ответственности

- `ConfluenceParser` выбирает актуальный S2T, но не скачивает и не парсит его.
- `MetadataSyncService` превращает найденный S2T в стабильный metadata snapshot.
- `IncrementalUpdater` принимает решение, нужно ли скачивать, парсить и обновлять RAG.
- `RAGIndexer` отвечает только за преобразование структурированных атрибутов в RAG-документы.
- `RAGRetriever` отвечает за выбор стратегии ответа на вопрос пользователя.

## Ограничения текущей реализации

- Локальный vector store — JSONL-файл, а не полноценная vector DB. Partial update реализован
  как замена документов конкретной витрины внутри JSONL.
- `build-rag --full` остается полной пересборкой и должен использоваться вручную.
- `update-rag` требует доступ к Confluence и корректные настройки `.env`.
