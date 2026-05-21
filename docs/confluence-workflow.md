# Confluence Integration

Документ описывает поток работы с Confluence: поиск страниц витрин, выбор актуального S2T,
сбор metadata через Confluence API, инкрементальное обновление локальной базы и RAG.

## Основные модули

### Confluence Client

HTTP-клиент для Confluence REST API.

Назначение:

- получает страницы витрин и дочерние страницы;
- получает вложения страницы;
- скачивает S2T-файлы;
- нормализует технические metadata Confluence в модели приложения.

Код:

- `app/confluence/client.py`
- `app/confluence/models.py`

Основные API-запросы:

```text
GET /rest/api/content/{page_id}
GET /rest/api/content/{page_id}/child/page
GET /rest/api/content/{page_id}/child/attachment
GET /rest/api/content/search
```

### Confluence Parser

Модуль поиска витрин и выбора актуального S2T.

Назначение:

- ищет страницы витрин по `DATAMART_PAGE_PATTERN`;
- извлекает stakeholders из тела страницы;
- находит S2T-кандидаты во вложениях, ссылках, таблицах и дочерних страницах;
- выбирает актуальный S2T по дате, маркеру `новый/latest`, версии и времени обновления;
- обогащает HTML/storage-кандидаты metadata из Confluence API.

Код:

- `app/confluence/parser.py`

Важное разделение ответственности:

- Confluence API является источником истины для технических metadata файла;
- HTML/storage body используется только для семантики страницы: где лежит S2T, какая строка
  таблицы считается актуальной, кто указан как stakeholder.

### Metadata Sync

Подсистема сборки стабильного metadata snapshot.

Назначение:

- вызывает `ConfluenceParser`;
- получает выбранный S2T для каждой витрины;
- формирует JSON metadata snapshot;
- считает стабильный `metadata_hash`.

Код:

- `app/sync/metadata_sync_service.py`
- `app/sync/hash_service.py`

### Incremental Updater

Подсистема metadata-first обновления локальной базы и RAG.

Назначение:

- сравнивает новый metadata snapshot с `s2t_state`;
- скачивает S2T только при изменении metadata;
- считает `sha256(content)`;
- парсит S2T только при изменении содержимого;
- обновляет `attributes`, `documents`, vector store и `change_log` только для затронутой витрины.

Код:

- `app/sync/incremental_updater.py`
- `app/sync/state_comparator.py`
- `app/storage/s2t_state_repository.py`

## Workflow

### 1. Инициализация и актуализация локальной базы

Перед ответами пользователя или по расписанию запускается обновление локального индекса:

```bash
.venv/bin/python -m app.cli update-rag
```

Проверка состояния:

- система читает `s2t_state` из SQLite;
- для каждого S2T-ресурса хранится последний `metadata_hash` и `content_hash`;
- если ресурс новый или metadata изменились, он попадает в план обновления.

Сбор metadata:

- через Confluence API запрашиваются страницы витрин;
- через Confluence API запрашиваются вложения;
- из API берутся `page_id`, `page_version`, `attachment_id`, `attachment_version`,
  `file_size`, `media_type`, `download_url`;
- HTML/storage body используется для поиска таблиц, ссылок и маркеров актуальности.

Результат:

- локальная база знает актуальное состояние S2T;
- неизмененные файлы не скачиваются;
- RAG обновляется только для витрин, где реально изменился S2T.

### 2. Фаза обнаружения Confluence-страниц

Page Discovery:

- если задан `CONFLUENCE_ROOT_PAGE_ID`, система берет дочерние страницы root page;
- иначе выполняется CQL-поиск по `CONFLUENCE_SPACE_KEY`;
- страницы фильтруются по `DATAMART_PAGE_PATTERN`.

Datamart Parsing:

- создается модель `Datamart`;
- сохраняются `confluence_page_id`, `confluence_url`, версия страницы и время изменения;
- из HTML/storage извлекаются stakeholders.

### 3. Фаза выбора S2T

Поиск выполняется несколькими способами:

А. Вложения через API

- `ConfluenceClient.get_attachments(page_id)` получает список файлов страницы;
- для каждого вложения доступны `id`, `title`, `version`, `fileSize`, `mediaType`,
  `downloadUrl`;
- это основной источник технических metadata.

Б. Таблицы и ссылки в storage body

- парсер ищет ссылки на `.xlsx`, `.xls`, `.csv`;
- рядом с датой в таблице ищется файл S2T;
- строка с маркером `новый`, `latest`, `актуальный` получает повышенный приоритет;
- если ссылка найдена в HTML, ресурс обогащается metadata соответствующего вложения из API.

В. Дочерние страницы S2T

- если дочерняя страница похожа на S2T-раздел, парсер проверяет ее HTML/storage body;
- вложения дочерней страницы также запрашиваются через API;
- найденные ссылки и таблицы обогащаются metadata вложений дочерней страницы.

Выбор актуального S2T:

```text
table_latest_row priority
-> file_date from title/table
-> updated_at from Confluence
-> версия вложения
```

### 4. Фаза сравнения metadata

Для выбранного S2T формируется snapshot:

```text
datamart_name
datamart_page_id
datamart_page_version
datamart_page_version_when
attachment_id
attachment_title
attachment_version_number
attachment_version_when
attachment_file_size
download_url
media_type
resource_type
resource_page_id
file_name
```

Далее считается:

```text
metadata_hash = sha256(stable_json(metadata))
```

Ветвление:

| Состояние                 | Действие                                                              |
| ---------------------------------- | ----------------------------------------------------------------------------- |
| Metadata не изменились | Пропустить download, parse и reindex.                              |
| Metadata изменились      | Скачать файл и проверить `content_hash`.               |
| Ресурс новый            | Скачать файл, распарсить и сохранить baseline. |

### 5. Фаза скачивания и парсинга S2T

Download:

- используется `download_url` из Confluence API;
- если `download_url` отсутствует, ресурс не может быть скачан автоматически;
- скачанный файл сохраняется в `data/raw`.

Content Check:

```text
content_hash = sha256(file_bytes)
```

Ветвление:

| Состояние                       | Действие                                          |
| ---------------------------------------- | --------------------------------------------------------- |
| `content_hash` не изменился | Обновить metadata state, не парсить S2T. |
| `content_hash` изменился      | Запустить `S2TParser`.                         |

S2T Parsing:

- `.xlsx` и `.xls` обрабатываются Excel parser;
- `.csv` обрабатывается CSV parser;
- результат сохраняется как структурированные атрибуты витрины.

### 6. Фаза обновления локального индекса

Metadata Store:

- `datamarts` обновляется данными витрины;
- `attributes` заменяются только для изменившейся витрины;
- старые атрибуты сравниваются с новыми через `DiffService`.

Change Log:

- добавленные, удаленные и измененные атрибуты записываются в `change_log`;
- первая baseline-загрузка не записывается как массовое добавление атрибутов.

RAG Update:

- `RAGIndexer.update_datamart` пересоздает документы только для одной витрины;
- `DocumentRepository` и `JsonVectorStore` заменяют chunks этой витрины;
- полный rebuild не нужен для штатного Confluence refresh.

State Update:

- `s2t_state` сохраняет новый `metadata_hash`, `content_hash`, `last_checked_at`,
  `last_synced_at`.

### 7. Фаза ответов пользователю

Bot Service:

- CLI, HTTP и SberChat adapter передают вопрос в общий сервис;
- `RAGRetriever` сначала пытается ответить структурно из SQLite;
- если точного structured ответа нет, используется vector search и LLM fallback.

Типовые structured-вопросы:

- кто владелец витрины;
- в каких витринах есть атрибут;
- из какого источника берется поле;
- какая логика преобразования;
- какие изменения были за последний год.

## Dry-run

Проверка поиска Confluence без обновления локального состояния:

```bash
.venv/bin/python -m app.cli parse-confluence --dry-run
```

Проверка инкрементального плана:

```bash
.venv/bin/python -m app.cli update-rag --dry-run
```

Dry-run показывает:

- какие S2T-ресурсы найдены;
- изменилась ли metadata;
- будет ли скачивание;
- будет ли парсинг;
- будет ли reindex;
- причины изменения metadata.

## Troubleshooting

| Проблема                                                | Возможная причина                                                                                                                | Что проверить                                                                                                                                |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ошибка 401/403 Confluence                                 | Неверный логин/token или нет прав на space/page.                                                                        | Проверить `CONFLUENCE_USERNAME`, `CONFLUENCE_API_TOKEN`, доступ к странице в браузере.                              |
| Confluence DNS/network error                                    | Нет доступа к корпоративной сети или VPN.                                                                         | Подключить VPN, проверить `CONFLUENCE_BASE_URL`.                                                                                    |
| Витрины не находятся                          | Неверный space/root/pattern.                                                                                                             | Проверить `CONFLUENCE_SPACE_KEY`, `CONFLUENCE_ROOT_PAGE_ID`, `DATAMART_PAGE_PATTERN`.                                                     |
| S2T не находится                                     | Файл не похож на S2T или лежит вне ожидаемой страницы.                                                  | Проверить `S2T_SECTION_PATTERNS`, наличие `.xlsx/.xls/.csv`, дочерние S2T-страницы.                                  |
| Выбрана старая S2T                                 | На странице нет даты/маркера актуальности или таблица оформлена нестандартно. | Проверить таблицу S2T в Confluence, маркеры `новый/latest/актуальный`, дату в названии файла. |
| Metadata изменилась, но RAG не обновился | Содержимое файла не изменилось, совпал `content_hash`.                                                        | Проверить отчет `.venv/bin/python -m app.cli update-rag --dry-run` и состояние `s2t_state`.                                                              |
| Файл найден, но не скачивается         | У ресурса нет `download_url` или ссылка не является вложением.                                          | Лучше прикрепить S2T как вложение Confluence, а не внешнюю ссылку.                                                    |
| Парсинг S2T падает                                 | Неожиданный формат Excel/CSV или отсутствуют нужные колонки.                                         | Проверить листы `Target columns`, `Source columns`, `Datamart info`, `S2T`.                                                        |
| Ответ говорит "данных нет"                 | Локальная база не обновлена или витрина не прошла фильтр.                                        | Запустить `.venv/bin/python -m app.cli update-rag --dry-run`, затем `.venv/bin/python -m app.cli update-rag`.                                                                                  |
| Изменения за год пустые                     | Была только baseline-загрузка или нет записей в `change_log`.                                                  | Проверить дату первой синхронизации и историю `change_log`.                                                    |
| GigaChat error                                                  | Неверные credentials/scope или недоступен LLM.                                                                              | Проверить `LLM_PROVIDER`, `GIGACHAT_CREDENTIALS`, `GIGACHAT_SCOPE`.                                                                       |

## Operational checklist

Перед регулярным запуском:

1. Заполнить `.env`.
2. Проверить доступ к Confluence через `.venv/bin/python -m app.cli parse-confluence --dry-run`.
3. Проверить план обновления через `.venv/bin/python -m app.cli update-rag --dry-run`.
4. Выполнить `.venv/bin/python -m app.cli update-rag`.
5. Задать smoke-вопрос через CLI или HTTP.

Для планировщика использовать:

```bash
.venv/bin/python -m app.cli update-rag
```

Не использовать для регулярного refresh:

```bash
.venv/bin/python -m app.cli build-rag --full
```
