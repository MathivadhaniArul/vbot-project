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

Choose either the **Local Setup** or the **Docker Setup** (recommended for simplified deployment).

---

### Method 1: Local Setup

#### 1. Clone the repository
```bash
git clone https://github.com/MathivadhaniArul/vbot-project.git
cd vbot-project
```

#### 2. Frontend Setup
```bash
# From the root directory
npm install
npm run dev
```
The frontend runs on: [http://localhost:3000](http://localhost:3000)

#### 3. Backend Setup
1. Create a `.env` file inside the `backend/` directory:
   ```env
   MONGO_URI=mongodb://localhost:27017
   OLLAMA_BASE_URL=http://127.0.0.1:11434
   ```
2. Make sure MongoDB is running locally on port `27017`.
3. Make sure Ollama is running and has the `llama3:8b` model pulled:
   ```bash
   ollama run llama3:8b
   ```
4. Install backend dependencies and run the server:
   ```bash
   cd backend
   pip install -r requirements.txt
   python main.py
   ```
The backend runs on: [http://localhost:8000](http://localhost:8000)

---

### Method 2: Docker Setup (Docker Compose)

The repository contains `Dockerfile`s for the frontend and backend, along with a `docker-compose.yml` to spin up the entire ecosystem (Next.js, FastAPI, and MongoDB).

#### 1. Setup Ollama on Host Machine
Ensure Ollama is running on your host machine. The Docker container will communicate with it via `http://host.docker.internal:11434`.
Make sure Ollama has the required model pulled:
```bash
ollama pull llama3:8b
```

#### 2. Run with Docker Compose
Simply run the following command from the root directory of the project:
```bash
docker compose up --build
```

This automatically orchestrates and starts:
- **Next.js Frontend**: on [http://localhost:3000](http://localhost:3000)
- **FastAPI Backend**: on [http://localhost:8000](http://localhost:8000)
- **MongoDB Database**: on port `27017` inside Docker.

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

## Usage Guide

### Using the Frontend
1. Open your browser and navigate to `http://localhost:3000`.
2. **Text Chat:** Type your queries in the chat input at the bottom and press Enter to chat with the RAG-enabled assistant.
3. **Voice Assistant:** 
   * Click on the microphone icon to start recording your voice.
   * Speak your query (the frontend uses **RecordRTC** to capture high-quality audio in WAV format).
   * Click the stop button to send the voice query. The backend will transcribe it, query the RAG pipeline, and respond.

### Using the Backend
1. **Interactive API Docs:** Navigate to `http://localhost:8000/docs` in your browser to access the interactive FastAPI Swagger UI. Here you can explore and test all API endpoints manually (e.g., chat endpoints, ingestion endpoints).
2. **Autonomous RAG Pipeline:** The backend runs a semi-automated RAG background pipeline. It automatically:
   * Periodically crawls websites (such as the Riviera 2026 event site) using hybrid static/SPA fetchers.
   * Detects changes using SHA-256 content hashes.
   * Splits modified content into chunks and generates embeddings.
   * Ingests the updated knowledge into the **Chroma DB** vector store.
3. **Data Verification:** You can check the current status of the background jobs and verify database stats via the API endpoints.

---

## Troubleshooting Notes

* **Port Conflicts:** If ports `3000` or `8000` are already in use, you can specify different ports.
  * For frontend: `npm run dev -- -p 3001`
  * For backend: `uvicorn main:app --reload --port 8001`
* **Vector DB Issues:** If Chroma DB is acting up or locked, delete the `backend/chroma/` directory and restart the backend to re-initialize it.
* **ModuleNotFoundError:** Ensure your Python virtual environment is activated before installing dependencies and running the server.
* **Missing Env Vars:** If you get errors related to MongoDB or Ollama, double-check that your `.env` file exists in the `backend/` directory and has the correct keys.

---

## Collaboration

1. Clone the repo (ensure you are using the existing collaborative repository).
2. Install frontend and backend dependencies as detailed above.
3. Add `.env` file to the backend.
4. Run frontend & backend servers.
5. Create a new branch for your feature, make sure not to commit secrets or cache files.

## License

This project is for educational purposes.
