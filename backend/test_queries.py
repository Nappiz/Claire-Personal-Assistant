import os
from services.llm_service import generate_search_queries

queries = [
    "kamu tau ga aku saat ini kuliah semester berapa dan dimana",
    "aku magang dimana?",
    "claire, coba tebak aku magang dimana",
    "claire, siapa sih yg nyiptain kamu"
]

for q in queries:
    print(f"Query: {q}")
    print(f"Keywords: {generate_search_queries(q)}")
    print("-" * 40)
