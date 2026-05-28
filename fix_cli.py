import re

file_path = 'app/cli.py'
with open(file_path, 'r') as f:
    content = f.read()

# Мы ищем место, где создается JiraClient в parse-confluence
old_block = """    jira_client = None
    if settings.jira_username and (settings.jira_token or settings.jira_api_token):
        jira_client = JiraClient(settings)"""

new_block = """    jira_client = None
    # Fix: Also check for jira_auth_token
    if settings.jira_auth_token or (settings.jira_username and (settings.jira_token or settings.jira_api_token)):
        import logging
        logging.getLogger(__name__).info("Initializing JiraClient...")
        jira_client = JiraClient(settings)
    else:
        import logging
        logging.getLogger(__name__).warning("Jira credentials not found in settings! jira_auth_token and (jira_username + jira_token) are missing.")"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(file_path, 'w') as f:
        f.write(content)
    print("Updated app/cli.py (parse_confluence)")
else:
    print("Could not find the target block in app/cli.py")


# Теперь обновляем то же самое для update-rag
old_block2 = """    jira_client = None
    if settings.jira_username and (settings.jira_token or settings.jira_api_token):
        jira_client = JiraClient(settings)"""

# Мы знаем, что блок встречается дважды, первый раз мы его уже заменили, 
# если используем .replace без count, то заменим все вхождения. Но так как 
# мы уже заменили первое, то ищем заново исходный файл.
