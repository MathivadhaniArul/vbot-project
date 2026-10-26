import json
import logging
import os
import re
from typing import Any

from dotenv import load_dotenv
from langchain_ollama import ChatOllama

load_dotenv()

logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://localhost:11435",
)

ROUTER_MODEL = os.getenv(
    "ROUTER_MODEL",
    "qwen3:8b-q4_K_M",
)

MAX_HISTORY_CHARS = 3000

VALID_SOURCES = {
    "qdrant",
    "reminder",
    "meta",
    "greeting",
}

SUPPORTED_LANGUAGES = {
    "en",
    "ta",
    "hi",
    "te",
    "kn",
    "ml",
}


# ============================================================
# LLM
# ============================================================

_router_llm = ChatOllama(
    model=ROUTER_MODEL,
    base_url=OLLAMA_BASE_URL,
    temperature=0,
    extra_body={
        "think": False,
    },
    timeout=90,
)


# ============================================================
# ROUTER SYSTEM PROMPT
# ============================================================

ROUTER_SYSTEM = """
You are the routing and language-detection component of a
multilingual VIT university chatbot.

Your job is ONLY to:

1. Detect the language of the LATEST user message.
2. Decide which source(s) should handle the request.

DO NOT:

- translate the user's query
- rewrite the user's query
- answer the user's question
- summarize the user's question
- generate an English version of the question

The original user query must remain unchanged for retrieval.

Return ONLY one valid JSON object.

Allowed sources:

- qdrant
- reminder
- meta
- greeting


============================================================
LANGUAGE DETECTION
============================================================

Detect the language of the LATEST USER MESSAGE.

Return the ISO-639-1 code in:

"detected_language"

Supported languages:

- en = English
- ta = Tamil
- hi = Hindi
- te = Telugu
- kn = Kannada
- ml = Malayalam

IMPORTANT:

Detect the LANGUAGE BEING SPOKEN, not merely the script.

Examples:

"Hostel fee deadline kab hai?"
=> hi

"hostel fee eppo pay pannanum?"
=> ta

"hostel fee deadline?"
=> en

"விடுதி கட்டணம் எப்போது செலுத்த வேண்டும்?"
=> ta

"हॉस्टल फीस कब भरनी है?"
=> hi

"హాస్టల్ ఫీజు ఎప్పుడు చెల్లించాలి?"
=> te

"ಹಾಸ್ಟೆಲ್ ಶುಲ್ಕವನ್ನು எப்போது செலுத்த வேண்டும்?"
=> kn

Tamil, Hindi, Telugu, Kannada, or Malayalam written using
Latin characters must still be detected as that language.

If a message is code-mixed:

- identify the dominant language of the actual sentence
- do not automatically classify it as English just because
  English words appear in it

Examples:

"hostel fee eppo pay pannanum?"
=> ta

"fees kab pay karna hai?"
=> hi

"SAP பற்றி சொல்லுங்கள்"
=> ta

"what is SAP என்று சொல்லுங்கள்"
=> ta

If the message contains only:

- an emoji
- a number
- a URL
- punctuation
- a bare name
- an acronym with no meaningful linguistic context

use "en" unless the language is otherwise clear.

ALWAYS detect the language of the LATEST USER MESSAGE.

Do not use the language of previous messages.

Previous conversation may be in English while the latest
message is Tamil, Hindi, Telugu, Kannada, or Malayalam.

The latest user message is the source of truth for
detected_language.


============================================================
CONVERSATION HISTORY
============================================================

Chat history is provided only as contextual information.

For LANGUAGE DETECTION:

ALWAYS prioritize the LATEST USER MESSAGE.

Do NOT copy the language of an earlier message.

Example:

Previous:
"What is hostel fee?"

Latest:
"அது எப்போது செலுத்த வேண்டும்?"

Detected language:
"ta"

The latest message controls the detected language.


============================================================
QDRANT
============================================================

Use qdrant when the user asks for VIT/university information.

Examples:

- regulations
- hostel
- admissions
- fees
- departments
- faculty
- counsellors
- committees
- clubs
- placements
- procedures
- campus services
- academic policies
- deadlines
- contact details
- courses
- examinations
- academic information
- scholarships
- academic calendars
- facilities
- programs
- university policies

If the user asks a follow-up question whose answer requires
VIT/university information, use qdrant.

Examples:

"What about eligibility?"

"How much is it?"

"When is it due?"

"Where do I apply?"

These should use qdrant when the conversation context
indicates that the question concerns VIT/university information.


============================================================
REMINDER
============================================================

Use reminder ONLY when the user explicitly asks the assistant
to remember or remind them about something.

Examples:

"I have a project review tomorrow. Remind me."

"Remind me to pay my fees."

"My chemistry exam is on June 18. Remind me."

If the user asks for university information AND a reminder,
use BOTH:

["qdrant", "reminder"]

Example:

"What is the fee deadline? Remind me one day before."

Output:

["qdrant", "reminder"]

If the user only wants a reminder and already provides the
event details:

["reminder"]

Do not use qdrant merely because the reminder mentions a
university event.


============================================================
META
============================================================

Use meta ONLY for questions about the chatbot itself.

Examples:

"Who are you?"

"What can you do?"

"What languages do you support?"

"Are you an AI?"

"What are your limitations?"


============================================================
GREETING
============================================================

Use greeting ONLY for a simple greeting or pleasantry with
NO other request.

Examples:

"Hi"

"Hello"

"Hey"

"Good morning"

"வணக்கம்"

If a greeting also contains a question, route according to
the actual question.

Example:

"Hi, what is the hostel fee?"

=> ["qdrant"]


============================================================
ROUTING PRIORITY
============================================================

Apply these rules:

1. University information:
   qdrant

2. Explicit reminder request:
   reminder

3. University information + explicit reminder:
   qdrant + reminder

4. Chatbot capability question:
   meta

5. Simple greeting only:
   greeting

Never invent another source.


============================================================
IMPORTANT RETRIEVAL RULE
============================================================

DO NOT translate the query.

DO NOT return a translated_query field.

The application will send the ORIGINAL user message directly
to the multilingual BGE-M3 retrieval model.

The application will also use the original question when
generating the final answer.

Your job is only routing and language detection.


============================================================
OUTPUT
============================================================

Return EXACTLY one JSON object:

{
  "sources": ["qdrant"],
  "reason": "Needs university information.",
  "detected_language": "ta"
}

Rules:

- sources must be a non-empty list
- every source must be one of:
  qdrant, reminder, meta, greeting
- do not duplicate sources
- reason must be a short sentence
- detected_language must be one of:
  en, ta, hi, te, kn, ml
- no markdown
- no code fences
- no explanation
- no text outside the JSON object
"""


# ============================================================
# RETRY PROMPT
# ============================================================

_RETRY_NUDGE = """
Your previous response was invalid.

Return ONLY ONE valid JSON object.

Required shape:

{
  "sources": ["qdrant"],
  "reason": "one short sentence",
  "detected_language": "ta"
}

Allowed sources:

qdrant
reminder
meta
greeting

detected_language MUST be one of:

en
ta
hi
te
kn
ml

Do not translate the query.

Do not include translated_query.

No markdown.
No code fences.
No explanation.
No extra text.
"""


# ============================================================
# LANGUAGE ALIASES
# ============================================================

LANGUAGE_ALIASES = {
    "english": "en",
    "tamil": "ta",
    "hindi": "hi",
    "telugu": "te",
    "kannada": "kn",
    "malayalam": "ml",

    "eng": "en",
    "tam": "ta",
    "hin": "hi",
    "tel": "te",
    "kan": "kn",
    "mal": "ml",
}


# ============================================================
# LANGUAGE NORMALIZATION
# ============================================================

def _normalize_language(value: Any) -> str:
    """
    Normalize an LLM language value.

    Unknown/unsupported languages fall back to English.
    """

    if not isinstance(value, str):
        return "en"

    lang = value.strip().lower()

    if not lang:
        return "en"

    lang = LANGUAGE_ALIASES.get(
        lang,
        lang,
    )

    if lang in SUPPORTED_LANGUAGES:
        return lang

    return "en"


# ============================================================
# LIGHTWEIGHT LOCAL LANGUAGE DETECTION
# ============================================================

def _detect_script_language(text: str) -> str | None:
    if re.search(r"[\u0B80-\u0BFF]", text):
        return "ta"

    if re.search(r"[\u0900-\u097F]", text):
        return "hi"

    if re.search(r"[\u0C00-\u0C7F]", text):
        return "te"

    if re.search(r"[\u0C80-\u0CFF]", text):
        return "kn"

    if re.search(r"[\u0D00-\u0D7F]", text):
        return "ml"

    return None


# ============================================================
# SOURCE VALIDATION
# ============================================================

def _validate_sources(sources: Any) -> bool:

    if not isinstance(sources, list):
        return False

    if not sources:
        return False

    if not all(
        isinstance(source, str)
        and source in VALID_SOURCES
        for source in sources
    ):
        return False

    return len(sources) == len(set(sources))


# ============================================================
# JSON EXTRACTION
# ============================================================

def _extract_json(raw: str) -> str:

    if not raw:
        raise ValueError(
            "Empty router response"
        )

    raw = raw.strip()

    # Qwen may return reasoning before </think>.
    if "</think>" in raw:
        raw = raw.split(
            "</think>",
            1,
        )[1].strip()

    # Remove markdown code fences.
    match = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        raw,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if match:
        return match.group(1).strip()

    # Extract JSON object surrounded by text.
    start = raw.find("{")
    end = raw.rfind("}")

    if start != -1 and end != -1 and end > start:
        return raw[
            start:end + 1
        ].strip()

    return raw


# ============================================================
# COMPLETE OUTPUT VALIDATION
# ============================================================

def _validate_router_output(data: Any) -> None:

    if not isinstance(data, dict):
        raise ValueError(
            "Router response must be a JSON object"
        )

    required_fields = {
        "sources",
        "reason",
        "detected_language",
    }

    missing = (
        required_fields
        - set(data.keys())
    )

    if missing:
        raise ValueError(
            f"Missing router fields: "
            f"{sorted(missing)}"
        )

    if not _validate_sources(
        data["sources"]
    ):
        raise ValueError(
            f"Invalid sources: "
            f"{data.get('sources')!r}"
        )

    if not isinstance(
        data["reason"],
        str,
    ):
        raise ValueError(
            "reason must be a string"
        )

    if not isinstance(
        data["detected_language"],
        str,
    ):
        raise ValueError(
            "detected_language must be a string"
        )


# ============================================================
# FALLBACK
# ============================================================

def _fallback_response(
    query: str,
) -> dict:

    script_language = _detect_script_language(query)

    language = (
        script_language
        if script_language
        else "en"
    )

    return {
        "sources": ["qdrant"],
        "reason": (
            "Router fallback to university retrieval."
        ),
        "detected_language": language,
    }


# ============================================================
# ROUTER
# ============================================================

async def route_query(
    query: str,
    chat_history: str = "",
) -> dict:

    query = (
        query or ""
    ).strip()

    # --------------------------------------------------------
    # Empty query
    # --------------------------------------------------------

    if not query:

        return {
            "sources": ["qdrant"],
            "reason": (
                "Empty query routed to retrieval."
            ),
            "detected_language": "en",
        }

    # --------------------------------------------------------
    # Deterministic script detection
    #
    # This gives us a reliable fallback if Qwen fails to
    # identify Tamil/Hindi/etc.
    # --------------------------------------------------------

    script_language = _detect_script_language(query)

    # --------------------------------------------------------
    # Prevent history from becoming too large.
    # --------------------------------------------------------

    if len(chat_history) > MAX_HISTORY_CHARS:
        chat_history = (
            chat_history[
                -MAX_HISTORY_CHARS:
            ]
        )

    # --------------------------------------------------------
    # Explicitly tell Qwen that the latest message is the
    # language source of truth.
    # --------------------------------------------------------

    user_content = (
        "Conversation history:\n"
        f"{chat_history}\n\n"
        "LATEST USER MESSAGE "
        "(use this message for language detection):\n"
        f"{query}\n\n"
        "IMPORTANT:\n"
        "Detect the language of the latest user message.\n"
        "Do not translate it.\n"
        "Do not answer it.\n"
    )

    messages = [
        {
            "role": "system",
            "content": ROUTER_SYSTEM,
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]

    max_attempts = 2
    last_error = None
    response = None

    for attempt in range(
        max_attempts
    ):

        try:

            response = await _router_llm.ainvoke(
                messages
            )

            raw = _extract_json(
                response.content
            )

            logger.debug(
                "[router] attempt=%d raw=%s",
                attempt + 1,
                raw,
            )

            data = json.loads(raw)

            _validate_router_output(
                data
            )

            # ------------------------------------------------
            # Normalize sources
            # ------------------------------------------------

            data["sources"] = list(
                dict.fromkeys(
                    data["sources"]
                )
            )

            # ------------------------------------------------
            # Normalize language
            # ------------------------------------------------

            llm_language = (
                _normalize_language(
                    data["detected_language"]
                )
            )

            # ------------------------------------------------
            # IMPORTANT:
            #
            # If the message has an unambiguous native script,
            # trust deterministic script detection over Qwen.
            #
            # This protects:
            #
            # Tamil -> English mistakes
            # Hindi -> English mistakes
            # Telugu -> English mistakes
            # Kannada -> English mistakes
            # Malayalam -> English mistakes
            # ------------------------------------------------

            if script_language:
                data["detected_language"] = script_language
            else:
                data["detected_language"] = _normalize_language(
        data["detected_language"]
    )

            logger.info(
                "[router] sources=%s "
                "language=%s "
                "llm_language=%s "
                "script_language=%s",
                data["sources"],
                data["detected_language"],
                llm_language,
                script_language,
            )

            return data

        except Exception as exc:

            last_error = exc

            logger.warning(
                "[router] attempt=%d failed: %s",
                attempt + 1,
                exc,
            )

            if attempt < max_attempts - 1:

                raw_reply = ""

                try:
                    if response is not None:
                        raw_reply = (
                            response.content
                            or ""
                        )
                except Exception:
                    pass

                messages.append(
                    {
                        "role": "assistant",
                        "content": raw_reply,
                    }
                )

                messages.append(
                    {
                        "role": "user",
                        "content": _RETRY_NUDGE,
                    }
                )

    # --------------------------------------------------------
    # FINAL FALLBACK
    # --------------------------------------------------------

    logger.error(
        "[router] all attempts failed: %s",
        last_error,
    )

    fallback = _fallback_response(
        query
    )

    logger.info(
        "[router] fallback=%s",
        fallback,
    )

    return fallback