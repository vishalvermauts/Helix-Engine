import tree_sitter
from tree_sitter import Language, Parser, Query
import tree_sitter_python

lang = Language(tree_sitter_python.language())
query = Query(lang, "(identifier) @id")
print("Query attributes:", dir(query))
