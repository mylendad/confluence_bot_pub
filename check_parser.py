import inspect
from app.confluence.parser import ConfluenceParser

print(f"File: {inspect.getfile(ConfluenceParser)}")
print(f"Init args: {inspect.signature(ConfluenceParser.__init__)}")
