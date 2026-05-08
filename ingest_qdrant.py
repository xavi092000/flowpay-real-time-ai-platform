from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from openai import OpenAI
import uuid
from dotenv import load_dotenv
from pathlib import Path
import os

client = QdrantClient(url="http://localhost:6333")

COLLECTION_NAME = "flowpay_rag_v1"

# 1. créer collection
client.recreate_collection(
    collection_name=COLLECTION_NAME,
    vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
)


load_dotenv(Path(__file__).resolve().parent / ".env")

# 2. client OpenAI
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 3. documents simples (tu peux améliorer plus tard)
documents = [
    {
        "text": "Liquidity stress occurs when order book depth drops significantly.",
        "category": "liquidity",
    },
    {
        "text": "Order flow imbalance reflects aggressive selling pressure in markets.",
        "category": "order_flow",
    },
    {
        "text": "High volatility leads to spread widening and execution risk.",
        "category": "volatility",
    },
    {
        "text": "Execution risk increases when bid-ask spread becomes unstable.",
        "category": "execution",
    },
]

points = []

for doc in documents:
    embedding = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=doc["text"],
    ).data[0].embedding

    points.append(
        PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                "text": doc["text"],
                "category": doc["category"],
                "document_title": "FlowPay Knowledge Base",
                "section_title": "Core Concepts",
                "source_file": "internal",
                "chunk_id": str(uuid.uuid4()),
            },
        )
    )

# 4. upload
client.upsert(
    collection_name=COLLECTION_NAME,
    points=points,
)

print("✅ Collection flowpay_rag_v1 créée et remplie")