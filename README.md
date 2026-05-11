# AI Chatbot (RAG-based)

A full-stack AI chatbot that answers questions using Retrieval-Augmented Generation (RAG).
Built with a modern stack combining Next.js frontend and FastAPI backend.

---

## Tech Stack

### Frontend

* Next.js (App Router)
* TypeScript
* Tailwind CSS
* shadcn/ui

### Backend

* FastAPI
* LangChain
* Ollama (LLM)
* Chroma (Vector Database)
* MongoDB (Chat storage)

---

##  Features

* Chat interface with persistent history
* RAG-based answers from documents
* Context-aware retrieval
* Web scraping + document indexing
* FastAPI backend with async support

---

## Project Structure

```
ai-chatbot/
│
├── app/                # Next.js app router
├── components/         # UI components (shadcn)
├── backend/            # FastAPI + RAG pipeline
│   ├── main.py
│   ├── scrape/
│   └── requirements.txt
│
├── public/
├── package.json
└── README.md
```

---

## Setup Instructions

### Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/ai-chatbot.git
cd ai-chatbot
```

---

### Frontend setup

```bash
npm install
npm run dev
```

Runs on: http://localhost:3000

---

### Backend setup

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Runs on: http://localhost:8000

---

## Environment Variables

Create a `.env` file inside `backend/`:

```env
MONGO_URI=mongodb://localhost:27017
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

---

## How it works

1. Documents are scraped and chunked
2. Chunks are embedded using HuggingFace embeddings
3. Stored in Chroma vector database
4. User query → retrieved relevant context
5. LLM (Ollama) generates answer based on context


## Important Notes

* `backend/chroma/` is ignored (vector DB is generated locally)
* `.next/` and `node_modules/` are not included in repo
* `.env` is not committed for security reasons

---

## Collaboration

1. Clone the repo
2. Install dependencies
3. Add `.env` file
4. Run frontend & backend

# Python virtual env
backend/new2/
venv/
.venv/
env/


## License

This project is for educational purposes.
