from sentence_transformers import SentenceTransformer
from configs.settings import settings
import numpy as np
import os
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

encoder = SentenceTransformer(settings.EMBEDDING_MODEL_NAME, local_files_only=True)

entities = ["nafiz", "21 tahun", "its surabaya", "backend developer", "agung sedayu group", "claire", "ai engineer"]
vectors = {
    entity: encoder.encode(f"passage: {entity}", normalize_embeddings=True)
    for entity in entities
}

def cos_sim(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

for i in range(len(entities)):
    for j in range(i+1, len(entities)):
        sim = cos_sim(vectors[entities[i]], vectors[entities[j]])
        print(f"'{entities[i]}' vs '{entities[j]}': {sim:.3f}")
