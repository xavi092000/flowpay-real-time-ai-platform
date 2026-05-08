import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient

from flowpay_quant_engine import compute_quant_decision, generate_demo_events


PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"


def load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


load_env()

COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "flowpay_rag_v1")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")

TOP_K = int(os.getenv("FLOWPAY_RAG_TOP_K", "5"))

EST_EMBED_COST_PER_1K_TOKENS = 0.00002
EST_CHAT_COST_PER_1K_TOKENS = 0.00015


def require_env(var_name: str) -> str:
    value = os.getenv(var_name)

    if not value:
        raise EnvironmentError(f"Missing required environment variable: {var_name}")

    return value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


def estimate_cost(input_text: str, output_text: str = "") -> dict[str, float]:
    input_tokens = estimate_tokens(input_text)
    output_tokens = estimate_tokens(output_text)

    embedding_cost = (input_tokens / 1000) * EST_EMBED_COST_PER_1K_TOKENS
    chat_cost = ((input_tokens + output_tokens) / 1000) * EST_CHAT_COST_PER_1K_TOKENS

    return {
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_embedding_cost_usd": round(embedding_cost, 8),
        "estimated_chat_cost_usd": round(chat_cost, 8),
        "estimated_total_cost_usd": round(embedding_cost + chat_cost, 8),
        "cost_method": "rough_character_based_estimate",
    }


def build_quant_aware_query(decision: dict[str, Any]) -> str:
    return (
        f"Explain why FlowPay recommended {decision.get('recommended_action')} "
        f"for a {decision.get('severity')} market state. "
        f"The dominant problem is {decision.get('dominant_problem')}. "
        f"The Market Risk Score is {decision.get('market_risk_score')}."
    )


def embed_query(client: OpenAI, query: str) -> list[float]:
    response = client.embeddings.create(
        model=OPENAI_EMBED_MODEL,
        input=query,
    )

    return response.data[0].embedding


def search_qdrant(
    qdrant: QdrantClient,
    query_vector: list[float],
    top_k: int = TOP_K,
) -> list[Any]:
    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    )

    return results.points


def calculate_retrieval_confidence(results: list[Any]) -> dict[str, Any]:
    if not results:
        return {
            "confidence_score": 0.0,
            "confidence_label": "low",
            "avg_similarity_score": 0.0,
            "top_similarity_score": 0.0,
            "category_count": 0,
            "categories": [],
            "warning": "No retrieval results returned.",
        }

    scores = [float(point.score or 0.0) for point in results]

    categories = {
        (point.payload or {}).get("category", "unknown")
        for point in results
    }

    top_score = max(scores)
    avg_score = sum(scores) / len(scores)
    score_spread = top_score - min(scores)
    category_count = len(categories)

    score_component = min(1.0, max(0.0, avg_score / 0.65))
    diversity_component = min(1.0, category_count / 3)
    spread_penalty = min(0.25, score_spread / 2)

    confidence = (
        0.75 * score_component
        + 0.25 * diversity_component
        - spread_penalty
    )

    confidence = max(0.0, min(1.0, confidence))

    if confidence >= 0.75:
        label = "high"
    elif confidence >= 0.50:
        label = "medium"
    else:
        label = "low"

    return {
        "confidence_score": round(confidence, 4),
        "confidence_label": label,
        "avg_similarity_score": round(avg_score, 4),
        "top_similarity_score": round(top_score, 4),
        "score_spread": round(score_spread, 4),
        "category_count": category_count,
        "categories": sorted(categories),
        "calibration_status": "heuristic_not_backtested",
    }


def build_context(results: list[Any]) -> str:
    if not results:
        return "NO_CONTEXT_RETRIEVED"

    context_blocks = []

    for rank, point in enumerate(results, start=1):
        payload = point.payload or {}

        text = payload.get("text", "")

        block = f"""
[Source {rank}]
Category: {payload.get("category", "unknown")}
Document: {payload.get("document_title", "unknown")}
Section: {payload.get("section_title", "unknown")}
Source File: {payload.get("source_file", "unknown")}
Chunk ID: {payload.get("chunk_id", "unknown")}
Similarity Score: {point.score}

Content:
{text}
""".strip()

        context_blocks.append(block)

    return "\n\n---\n\n".join(context_blocks)


def build_prompt(
    decision: dict[str, Any],
    retrieval_query: str,
    context: str,
    retrieval_confidence: dict[str, Any],
) -> list[dict[str, str]]:
    system_prompt = """
You are FlowPay's production-grade RAG explanation assistant.

MISSION:
Explain and contextualize decisions made by FlowPay's deterministic quant engine with strict grounding, governance safety, and measurable confidence.

HARD CONSTRAINTS:
- You are NOT the decision-maker.
- You must NEVER override, modify, replace, or reinterpret the quant decision.
- You must ONLY use:
  1. the provided quant decision object
  2. the retrieved context
  3. the retrieval confidence metadata
- Do NOT use outside knowledge.
- Do NOT invent facts, metrics, causal relationships, market behavior, or business outcomes.
- Do NOT make forward-looking claims about market outcomes.

GOVERNANCE SAFETY RULE:
If the user asks you to ignore, override, replace, bypass, or strengthen the quant decision, say exactly:
"I cannot override or modify the quant engine decision."
Then say:
"The RAG layer is only authorized to explain and contextualize decisions, not change them."

INSUFFICIENT CONTEXT RULE:
If the retrieved context is insufficient, say exactly:
"The retrieved context is insufficient to answer with confidence."

CLAIM LABELING RULE:
Each claim must be labeled as:
- [Supported by context]
- [Supported by decision object]
- [Interpretation]
- [Uncertainty]

OUTPUT FORMAT:

### 1. Decision Summary
### 2. Supported Evidence
### 3. FlowPay Interpretation
### 4. Uncertainty / Limits
### 5. Business / Platform Impact
### 6. Confidence

Confidence format:
Confidence Score: X.XX
Confidence Rationale:
- Factor 1
- Factor 2
- Factor 3
""".strip()

    user_prompt = f"""
Quant decision object:
{json.dumps(decision, indent=2)}

Retrieval query:
{retrieval_query}

Retrieval confidence metadata:
{json.dumps(retrieval_confidence, indent=2)}

Retrieved context:
{context}

Explain the quant decision using only the decision object, retrieval confidence metadata, and retrieved context.
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def generate_answer(client: OpenAI, messages: list[dict[str, str]]) -> str:
    response = client.chat.completions.create(
        model=OPENAI_CHAT_MODEL,
        messages=messages,
        temperature=0.2,
    )

    return response.choices[0].message.content or ""


def print_sources(results: list[Any]) -> None:
    print("\n=== SOURCES USED ===")

    if not results:
        print("No sources retrieved.")
        return

    for rank, point in enumerate(results, start=1):
        payload = point.payload or {}

        score = float(point.score or 0.0)

        print(
            f"{rank}. {payload.get('document_title', 'unknown')} "
            f"| category={payload.get('category', 'unknown')} "
            f"| score={score:.4f} "
            f"| file={payload.get('source_file', 'unknown')}"
        )


def write_log(record: dict[str, Any]) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = LOG_DIR / f"flowpay_real_quant_rag_{timestamp}.json"

    with output_file.open("w", encoding="utf-8") as file:
        json.dump(record, file, indent=2, ensure_ascii=False)

    return output_file


def build_log_record(
    decision: dict[str, Any],
    retrieval_query: str,
    results: list[Any],
    retrieval_confidence: dict[str, Any],
    answer: str,
    cost: dict[str, float],
    latency: dict[str, float],
    status: str,
    error_message: str | None = None,
) -> dict[str, Any]:
    source_records = []

    for rank, point in enumerate(results, start=1):
        payload = point.payload or {}

        source_records.append(
            {
                "rank": rank,
                "score": point.score,
                "category": payload.get("category"),
                "document_title": payload.get("document_title"),
                "section_title": payload.get("section_title"),
                "source_file": payload.get("source_file"),
                "chunk_id": payload.get("chunk_id"),
            }
        )

    return {
        "timestamp_utc": utc_now_iso(),
        "project": "flowpay-ai-platform",
        "pipeline_stage": "real_quant_decision_rag_explanation",
        "status": status,
        "error_message": error_message,
        "decision": decision,
        "retrieval_query": retrieval_query,
        "collection": COLLECTION_NAME,
        "qdrant_url": QDRANT_URL,
        "embedding_model": OPENAI_EMBED_MODEL,
        "chat_model": OPENAI_CHAT_MODEL,
        "top_k": TOP_K,
        "retrieval_confidence": retrieval_confidence,
        "sources": source_records,
        "answer": answer,
        "estimated_cost": cost,
        "latency_seconds": latency,
    }


def run_flowpay_rag(decision: dict[str, Any]) -> dict[str, Any]:
    openai_api_key = require_env("OPENAI_API_KEY")

    openai_client = OpenAI(api_key=openai_api_key)
    qdrant_client = QdrantClient(url=QDRANT_URL)

    start_total = time.perf_counter()

    latency: dict[str, float] = {}

    # 1. Query
    retrieval_query = build_quant_aware_query(decision)

    # 2. Embedding
    start_embedding = time.perf_counter()
    query_vector = embed_query(openai_client, retrieval_query)
    latency["embedding"] = round(time.perf_counter() - start_embedding, 4)

    # 3. Retrieval
    start_retrieval = time.perf_counter()
    results = search_qdrant(qdrant_client, query_vector, TOP_K)
    latency["retrieval"] = round(time.perf_counter() - start_retrieval, 4)

    # 4. Context + confidence
    retrieval_confidence = calculate_retrieval_confidence(results)
    context = build_context(results)

    # 5. Prompt
    messages = build_prompt(
        decision=decision,
        retrieval_query=retrieval_query,
        context=context,
        retrieval_confidence=retrieval_confidence,
    )

    # 6. Generation
    start_generation = time.perf_counter()
    answer = generate_answer(openai_client, messages)
    latency["generation"] = round(time.perf_counter() - start_generation, 4)

    # 7. Cost
    prompt_text = json.dumps(messages, ensure_ascii=False)
    cost = estimate_cost(input_text=prompt_text, output_text=answer)

    latency["total"] = round(time.perf_counter() - start_total, 4)

    return {
        "explanation": answer,
        "retrieval_confidence": retrieval_confidence,
        "cost": cost,
        "latency": latency,
        "sources": [
            {
                "score": point.score,
                "category": (point.payload or {}).get("category"),
                "document_title": (point.payload or {}).get("document_title"),
            }
            for point in results
        ],
    }








def main() -> None:
    start_total = time.perf_counter()

    decision: dict[str, Any] = {}
    retrieval_query = ""
    results: list[Any] = []
    retrieval_confidence: dict[str, Any] = {}
    answer = ""
    cost: dict[str, float] = {}
    latency: dict[str, float] = {}

    try:
        openai_api_key = require_env("OPENAI_API_KEY")

        openai_client = OpenAI(api_key=openai_api_key)
        qdrant_client = QdrantClient(url=QDRANT_URL)

        print("\nFlowPay Real Quant + RAG Decision Explanation")
        print("This version computes the quant decision from event data.\n")

        events = generate_demo_events()

        start_quant = time.perf_counter()
        decision = compute_quant_decision(
            events=events,
            previous_mrs_values=[22.5, 28.1, 31.4],
        )
        latency["quant_engine"] = round(time.perf_counter() - start_quant, 4)

        retrieval_query = build_quant_aware_query(decision)

        start_embedding = time.perf_counter()
        query_vector = embed_query(openai_client, retrieval_query)
        latency["embedding"] = round(time.perf_counter() - start_embedding, 4)

        start_retrieval = time.perf_counter()
        results = search_qdrant(qdrant_client, query_vector, TOP_K)
        latency["retrieval"] = round(time.perf_counter() - start_retrieval, 4)

        retrieval_confidence = calculate_retrieval_confidence(results)
        context = build_context(results)

        messages = build_prompt(
            decision=decision,
            retrieval_query=retrieval_query,
            context=context,
            retrieval_confidence=retrieval_confidence,
        )

        prompt_text = json.dumps(messages, ensure_ascii=False)

        start_generation = time.perf_counter()
        answer = generate_answer(openai_client, messages)
        latency["generation"] = round(time.perf_counter() - start_generation, 4)

        cost = estimate_cost(input_text=prompt_text, output_text=answer)

        latency["total"] = round(time.perf_counter() - start_total, 4)

        log_record = build_log_record(
            decision=decision,
            retrieval_query=retrieval_query,
            results=results,
            retrieval_confidence=retrieval_confidence,
            answer=answer,
            cost=cost,
            latency=latency,
            status="success",
        )

        log_file = write_log(log_record)

        print("=" * 80)
        print("FLOWPAY REAL QUANT DECISION")
        print("=" * 80)
        print(json.dumps(decision, indent=2))

        print("\n" + "=" * 80)
        print("FLOWPAY RAG EXPLANATION")
        print("=" * 80)
        print(answer)

        print("\n=== RETRIEVAL CONFIDENCE ===")
        print(json.dumps(retrieval_confidence, indent=2))

        print("\n=== ESTIMATED COST ===")
        print(json.dumps(cost, indent=2))

        print("\n=== LATENCY SECONDS ===")
        print(json.dumps(latency, indent=2))

        print_sources(results)

        print(f"\nLog written to: {log_file}")
        print("=" * 80)

    except Exception as exc:
        latency["total"] = round(time.perf_counter() - start_total, 4)

        error_message = f"{type(exc).__name__}: {exc}"

        log_record = build_log_record(
            decision=decision,
            retrieval_query=retrieval_query,
            results=results,
            retrieval_confidence=retrieval_confidence,
            answer=answer,
            cost=cost,
            latency=latency,
            status="failed",
            error_message=error_message,
        )

        log_file = write_log(log_record)

        print("\nERROR WHILE RUNNING FLOWPAY REAL QUANT + RAG PIPELINE")
        print(error_message)
        print(f"Failure log written to: {log_file}")

        raise


if __name__ == "__main__":
    main()