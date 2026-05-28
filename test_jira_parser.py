import asyncio
from datetime import datetime
from app.confluence.models import ReleaseChange
from app.confluence.parser import ConfluenceParser

class MockJiraClient:
    def get_field_mapping(self):
        return {}
        
    def get_issue(self, issue_key):
        return {
            "fields": {
                "created": "2025-10-01T10:00:00.000+0300"
            },
            "changelog": {
                "histories": [
                    {
                        "created": "2025-10-15T14:04:57.000+0300",
                        "items": [
                            {
                                "field": "resolution",
                                "fieldtype": "jira",
                                "fieldId": "resolution",
                                "from": None,
                                "fromString": None,
                                "to": "10000",
                                "toString": "Done"
                            }
                        ]
                    }
                ]
            }
        }

parser = ConfluenceParser(client=None, settings=None, jira_client=MockJiraClient())
change = ReleaseChange(jira_key="TEST-123", change_type="ИЗМЕНЕНИЕ")
parser.enrich_release_changes([change])

print(f"Created: {change.jira_created_at}")
print(f"Done: {change.jira_done_at}")
