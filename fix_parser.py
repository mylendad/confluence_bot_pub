import re

parser_path = "app/confluence/parser.py"
with open(parser_path, "r") as f:
    content = f.read()

# 1. Update _release_page_from_link
old_release_page = """    def _release_page_from_link(self, page: ConfluencePage, html: str) -> ConfluencePage | None:
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a"):
            title = link.get_text(" ", strip=True)
            href = link.get("href")
            if not href or "изменения в релизах" not in normalize_text(title):
                continue
            page_id = self._page_id_from_url(href)
            if not page_id:
                continue
            try:
                return self.client.get_page(page_id)
            except Exception:
                logger.warning("Cannot load release changes page %s for %s", href, page.title)
                return None
        return None"""

new_release_page = """    def _release_page_from_link(self, page: ConfluencePage, html: str) -> ConfluencePage | None:
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a"):
            title = link.get_text(" ", strip=True)
            href = link.get("href")
            if not href:
                continue
            
            norm_title = normalize_text(title)
            if not any(kw in norm_title for kw in ["изменения в релизах", "журнал изменений", "список изменений", "история изменений"]):
                continue
                
            page_id = self._page_id_from_url(href)
            if not page_id:
                continue
                
            logger.info(f"Found release changes link '{title}' on page '{page.title}'")
            try:
                return self.client.get_page(page_id)
            except Exception:
                logger.warning("Cannot load release changes page %s for %s", href, page.title)
                return None
        return None"""

content = content.replace(old_release_page, new_release_page)


# 2. Update parse_release_changes_page
old_parse = """    def parse_release_changes_page(
        self, html: str, source_url: str | None = None
    ) -> list[ReleaseChange]:
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find(id="main-content") or soup
        changes: list[ReleaseChange] = []
        current_version: str | None = None
        pending_jira_key: str | None = None
        pending_jira_title: str | None = None
        pending_status: str | None = None
        for node in content.find_all(["h1", "h2", "h3", "p", "ul", "ol"], recursive=False):
            if node.name in {"h1", "h2", "h3"}:
                text = self._clean_text(node.get_text(" ", strip=True))
                if self._jira_key_from_node(node) and "версия" not in normalize_text(text):
                    continue
                if text:
                    current_version = text
                    pending_jira_key = None
                    pending_jira_title = None
                    pending_status = None
                continue
            if not current_version:
                continue
            jira_key = self._jira_key_from_node(node)
            jira_title = self._jira_title_from_node(node)
            status = self._jira_status_from_node(node)
            if jira_key:
                pending_jira_key = jira_key
                pending_jira_title = jira_title
                pending_status = status
            items = node.find_all("li", recursive=False) if node.name in {"ul", "ol"} else []
            if not items:
                continue
            for item in items:
                item_jira_key = self._jira_key_from_node(item) or jira_key or pending_jira_key
                change_type = self._release_change_type(item)
                summary = self._release_summary(item, change_type)
                if not any([item_jira_key, change_type, summary]):
                    continue
                changes.append(
                    ReleaseChange(
                        version=current_version,
                        jira_key=item_jira_key,
                        jira_title=self._jira_title_from_node(item)
                        or jira_title
                        or pending_jira_title,
                        change_type=change_type,
                        summary=summary,
                        status=self._jira_status_from_node(item) or status or pending_status,
                        source_url=source_url,
                    )
                )
            pending_jira_key = None
            pending_jira_title = None
            pending_status = None
        return changes"""

new_parse = """    def parse_release_changes_page(
        self, html: str, source_url: str | None = None
    ) -> list[ReleaseChange]:
        soup = BeautifulSoup(html, "html.parser")
        
        # In Confluence, main content might be nested deep inside layouts, columns, or macros
        # So we search globally, not just at the top level
        changes: list[ReleaseChange] = []
        
        # We will iterate over all list items. For each list item, we look backwards to find the nearest header
        # that looks like a version.
        headers = soup.find_all(["h1", "h2", "h3", "h4", "p"])
        list_items = soup.find_all("li")
        
        for item in list_items:
            # 1. Find the version header (closest preceding header or paragraph with version info)
            current_version = None
            for prev in item.find_previous_siblings(["h1", "h2", "h3", "h4", "p"]):
                text = self._clean_text(prev.get_text(" ", strip=True))
                norm_text = normalize_text(text)
                
                # Check if it looks like a version header
                if "версия" in norm_text or "релиз" in norm_text or re.search(r'202[0-9]', norm_text):
                     # ensure it's not just a random sentence mentioning version
                     if len(text) < 100: 
                         current_version = text
                         break
            
            if not current_version:
                # Let's try searching up the parent tree if previous siblings failed
                parent = item.find_parent()
                while parent and parent.name not in ['body', 'html']:
                    for prev in parent.find_previous_siblings(["h1", "h2", "h3", "h4", "p"]):
                        text = self._clean_text(prev.get_text(" ", strip=True))
                        norm_text = normalize_text(text)
                        if "версия" in norm_text or "релиз" in norm_text or re.search(r'202[0-9]', norm_text):
                             if len(text) < 100: 
                                 current_version = text
                                 break
                    if current_version:
                        break
                    parent = parent.find_parent()
            
            # If we STILL didn't find a version, skip or use a default (let's use default to at least capture it)
            if not current_version:
                current_version = "Неизвестная версия"
            
            # 2. Extract Jira Task
            # It might be directly in the <li> or in a parent element (like a paragraph preceding the list)
            item_jira_key = self._jira_key_from_node(item)
            jira_title = self._jira_title_from_node(item)
            status = self._jira_status_from_node(item)
            
            if not item_jira_key:
                # Look at the immediate parent or previous sibling of the parent <ul>
                parent_ul = item.find_parent(["ul", "ol"])
                if parent_ul:
                    prev_node = parent_ul.find_previous_sibling()
                    if prev_node:
                        item_jira_key = self._jira_key_from_node(prev_node)
                        if not jira_title:
                            jira_title = self._jira_title_from_node(prev_node)
                        if not status:
                            status = self._jira_status_from_node(prev_node)
            
            # 3. Extract Change Type (Macro or specific text)
            change_type = self._release_change_type(item)
            
            # 4. Extract Summary
            summary = self._release_summary(item, change_type)
            
            # We must have at least a Jira key or a change type to consider it a valid release change item
            if not item_jira_key and not change_type:
                continue
                
            changes.append(
                ReleaseChange(
                    version=current_version,
                    jira_key=item_jira_key,
                    jira_title=jira_title,
                    change_type=change_type,
                    summary=summary,
                    status=status,
                    source_url=source_url,
                )
            )
            
        return changes"""

content = content.replace(old_parse, new_parse)

with open(parser_path, "w") as f:
    f.write(content)
print("Applied deep parsing fixes via script")
