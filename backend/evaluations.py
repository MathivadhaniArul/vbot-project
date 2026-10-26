"""RAG-quality evaluation via RAGAS, run as a Celery batch job.

Reference-free only (faithfulness, answer_relevancy) since there's no
curated ground-truth Q&A set — these two don't need one:

  - faithfulness:      is the answer actually grounded in the retrieved
                        contexts, or is the model making things up?
  - answer_relevancy:  does the answer actually address the question
                        asked, or is it off-topic/non-committal?

Runs on a schedule (see celery_app.py beat_schedule) sampling recent
live traffic from `pipeline_metrics`, and can also be triggered manually
via POST /api/admin/evaluations/run for ad-hoc checks (e.g. after a
prompt or model change).

Deliberately NOT run inline in the /api/chat request path — the judge
LLM calls this makes (2 LLM calls per sample) would add real latency
and cost to every user message for zero user-facing benefit.
"""

import logging
import os
import sys
import types
from datetime import datetime, timedelta, timezone

from celery_app import celery_app
from dotenv import load_dotenv
from pymongo import MongoClient

# --- Compat shim for ragas 0.4.3 -----------------------------------------
# ragas/llms/base.py does an unconditional
#   `from langchain_community.chat_models.vertexai import ChatVertexAI`
# at import time. That path was removed from langchain-community once
# ChatVertexAI moved to the separate langchain-google-vertexai package,
# so importing ragas crashes for every user, VertexAI or not — regardless
# of which ragas API (old evaluate() or new collections) you actually use.
# https://github.com/vibrantlabsai/ragas/issues/2745
# Fix: register a fake module at the old import path that re-exports the
# real class from its new home, before anything imports ragas.
if "langchain_community.chat_models.vertexai" not in sys.modules:
    try:
        from langchain_google_vertexai import ChatVertexAI as _ShimChatVertexAI

        _shim = types.ModuleType("langchain_community.chat_models.vertexai")
        _shim.ChatVertexAI = _ShimChatVertexAI
        sys.modules["langchain_community.chat_models.vertexai"] = _shim
    except ImportError:
        # langchain-google-vertexai isn't installed either — fall back to
        # a stub class so the import still succeeds; nothing in this file
        # ever actually uses VertexAI, so it's never instantiated.
        _shim = types.ModuleType("langchain_community.chat_models.vertexai")

        class _ShimChatVertexAI:  # noqa: D401 - unused placeholder
            def __init__(self, *args, **kwargs):
                raise RuntimeError(
                    "ChatVertexAI shim invoked — VertexAI isn't configured "
                    "in this project; this stub only exists to satisfy "
                    "ragas's import-time dependency."
                )

        _shim.ChatVertexAI = _ShimChatVertexAI
        sys.modules["langchain_community.chat_models.vertexai"] = _shim
# ---------------------------------------------------------------------------

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_ollama import ChatOllama
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

logger = logging.getLogger(__name__)

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "chatbot_db")

mongo_client = MongoClient(MONGO_URL, tz_aware=True)
db = mongo_client[MONGO_DB]
pipeline_metrics = db["pipeline_metrics"]
rag_evaluations = db["rag_evaluations"]

# Same local Ollama model already used for generation in main.py — no
# separate API key/cost needed. A worker-process-local instance; not
# shared with the FastAPI process, which is fine since Celery tasks run
# in their own process regardless.
_JUDGE_MODEL = os.getenv("RAG_EVAL_JUDGE_MODEL", "qwen3:8b-q4_K_M")
_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11435")

# Deliberately NOT reusing main.py's LocalBGEM3Embeddings here: that
# class loads a full BGE-M3 model onto GPU/CPU, and duplicating it in
# this separate Celery worker process would double GPU memory usage for
# a judge task that doesn't need retrieval-grade embeddings — a small
# standalone sentence-transformer is enough for RAGAS's semantic
# similarity check inside answer_relevancy.
_EMBEDDING_MODEL = os.getenv(
    "RAG_EVAL_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)

_ragas_llm = None
_ragas_embeddings = None


def _get_ragas_llm():
    global _ragas_llm
    if _ragas_llm is None:
        _ragas_llm = LangchainLLMWrapper(
            ChatOllama(
                model=_JUDGE_MODEL,
                base_url=_OLLAMA_BASE_URL,
                temperature=0,
                extra_body={"think": False},
                timeout=120,
            )
        )
    return _ragas_llm


def _get_ragas_embeddings():
    global _ragas_embeddings
    if _ragas_embeddings is None:
        _ragas_embeddings = LangchainEmbeddingsWrapper(
            HuggingFaceEmbeddings(model_name=_EMBEDDING_MODEL)
        )
    return _ragas_embeddings


def _now():
    return datetime.now(timezone.utc)


@celery_app.task(bind=True, max_retries=1)
def run_rag_evaluation_batch(self, hours: int = 24, sample_size: int = 100):
    """Sample recent qdrant-sourced live chat responses that haven't
    been evaluated yet, score them with RAGAS, and persist results.
    """
    since = _now() - timedelta(hours=hours)

    match = {
        "createdAt": {"$gte": since},
        "sources": "qdrant",
        "answer": {"$ne": None},
        "contexts": {"$ne": None, "$not": {"$size": 0}},
        "rag_evaluated_at": None,
    }

    pipeline = [
        {"$match": match},
        {"$sample": {"size": sample_size}},
    ]
    samples = list(pipeline_metrics.aggregate(pipeline))

    if not samples:
        logger.info("[rag_eval] no unevaluated samples in the last %sh", hours)
        return {"status": "no_samples", "evaluated": 0}

    dataset = Dataset.from_dict({
        "question": [s["query"] for s in samples],
        "answer": [s["answer"] for s in samples],
        "contexts": [s["contexts"] for s in samples],
    })

    try:
        result = evaluate(
            dataset,
            metrics=[faithfulness, answer_relevancy],
            llm=_get_ragas_llm(),
            embeddings=_get_ragas_embeddings(),
        )
    except Exception as exc:
        logger.exception("[rag_eval] RAGAS evaluation batch failed")
        # Retry once — judge-LLM calls occasionally time out under load.
        raise self.retry(exc=exc, countdown=60)

    scored = result.to_pandas()
    now = _now()
    docs_to_insert = []
    evaluated_ids = []

    for i, sample in enumerate(samples):
        row = scored.iloc[i]
        docs_to_insert.append({
            "pipeline_metrics_id": str(sample["_id"]),
            "chatId": sample.get("chatId"),
            "userId": sample.get("userId"),
            "query": sample.get("query"),
            "faithfulness": (
                float(row["faithfulness"])
                if row.get("faithfulness") == row.get("faithfulness")  # NaN check
                else None
            ),
            "answer_relevancy": (
                float(row["answer_relevancy"])
                if row.get("answer_relevancy") == row.get("answer_relevancy")
                else None
            ),
            "createdAt": now,
        })
        evaluated_ids.append(sample["_id"])

    if docs_to_insert:
        rag_evaluations.insert_many(docs_to_insert)

    # Mark these source rows as evaluated so the next scheduled run
    # samples fresh traffic instead of re-scoring the same responses.
    pipeline_metrics.update_many(
        {"_id": {"$in": evaluated_ids}},
        {"$set": {"rag_evaluated_at": now}},
    )

    avg_faithfulness = scored["faithfulness"].dropna().mean()
    avg_relevancy = scored["answer_relevancy"].dropna().mean()

    logger.info(
        "[rag_eval] evaluated=%d avg_faithfulness=%.3f avg_answer_relevancy=%.3f",
        len(docs_to_insert),
        avg_faithfulness if avg_faithfulness == avg_faithfulness else -1,
        avg_relevancy if avg_relevancy == avg_relevancy else -1,
    )

    return {
        "status": "completed",
        "evaluated": len(docs_to_insert),
        "avg_faithfulness": None if avg_faithfulness != avg_faithfulness else round(avg_faithfulness, 3),
        "avg_answer_relevancy": None if avg_relevancy != avg_relevancy else round(avg_relevancy, 3),
    }