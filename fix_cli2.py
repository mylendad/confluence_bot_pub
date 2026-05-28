import re

file_path = 'app/cli.py'
with open(file_path, 'r') as f:
    content = f.read()

# Фиксим все оставшиеся вхождения старой логики (в update_rag)
content = re.sub(
    r'jira_client = None\s+if settings\.jira_username and \(settings\.jira_token or settings\.jira_api_token\):\s+jira_client = JiraClient\(settings\)',
    r'jira_client = None\n    if settings.jira_auth_token or (settings.jira_username and (settings.jira_token or settings.jira_api_token)):\n        jira_client = JiraClient(settings)',
    content
)

with open(file_path, 'w') as f:
    f.write(content)
print("Updated app/cli.py (update_rag)")
