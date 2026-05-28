import re

file_path = 'app/confluence/parser.py'
with open(file_path, 'r') as f:
    content = f.read()

old_block = """    def enrich_release_changes(self, changes: list[ReleaseChange]) -> None:
        if not self.jira_client:
            return
        field_mapping = self.jira_client.get_field_mapping()
        for change in changes:
            if not change.jira_key:
                continue"""

new_block = """    def enrich_release_changes(self, changes: list[ReleaseChange]) -> None:
        if not self.jira_client:
            logger.warning("JiraClient is None. Skipping Jira enrichment.")
            return
        field_mapping = self.jira_client.get_field_mapping()
        logger.info(f"Enriching {len(changes)} release changes with Jira data...")
        for change in changes:
            if not change.jira_key:
                continue
            logger.info(f"Fetching Jira issue: {change.jira_key}")"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(file_path, 'w') as f:
        f.write(content)
    print("Added debug logging to parser.py")
else:
    print("Could not find the target block in parser.py")
