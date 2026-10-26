# Lingua Bridge — local GPU deployment (Ollama)

Two-way translating chat, served off your own GPU via Ollama's
`qwen3:8b-q4_K_M`. Ollama serves the model, FastAPI bridges the two chat
sides over WebSocket and calls Ollama's OpenAI-compatible endpoint for
each translation, and a static frontend renders the chat.

## 0. Prerequisites

- Ollama installed and the model already pulled/running:
  ```bash
  ollama run qwen3:8b-q4_K_M
  ```
  (You can exit the interactive prompt with `/bye` — the model server
  keeps running in the background on port 11434.)
- Docker installed on the same machine.

Confirm Ollama is reachable and serving the OpenAI-compatible API:
```bash
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:8b-q4_K_M",
    "messages": [
      {"role":"system","content":"Translate from English to French. Reply with ONLY the translation."},
      {"role":"user","content":"How is your day going?"}
    ]
  }'
```
If that returns a translated sentence, you're ready.

## 1. Start the backend

From this project's root directory:
```bash
docker compose up --build
```

The backend container reaches your host's Ollama through
`host.docker.internal:11434` — no separate model-server container needed,
since Ollama is already running the model for you.

> Linux note: `extra_hosts: host.docker.internal:host-gateway` is already
> set in docker-compose.yml so this resolves correctly. On Docker Desktop
> (Mac/Windows) it works out of the box.

## 2. Open the chat

Visit `http://<gpu-machine-ip>:8080` in a browser. The page shows both
Person A and Person B panes — pick a language for each side, and messages
typed on one side appear translated on the other.

## 3. If the backend can't reach Ollama

- Make sure Ollama is bound to all interfaces, not just localhost, if
  Docker's bridge network can't reach it: set `OLLAMA_HOST=0.0.0.0` before
  starting Ollama, or run `systemctl edit ollama` to add it permanently.
- Re-run the curl check in step 0 from inside the backend container to
  isolate whether it's a Docker networking issue or a model issue:
  ```bash
  docker compose exec backend curl http://host.docker.internal:11434/v1/chat/completions ...
  ```

## 4. Notes on this model size

`qwen3:8b-q4_K_M` is lighter than the 14B setup this project started
with — expect faster responses and lower VRAM use, with a modest quality
trade-off on nuanced or slang-heavy text. If translation quality matters
more than speed for your use case, `qwen3:14b` or `qwen3:8b` at a higher
quant (`q8_0`) are easy swaps — just `ollama pull` the new tag and update
`MODEL_NAME` in docker-compose.yml.

## 5. Next steps once this is working

- Swap the in-memory translation cache in `backend/main.py` for Redis if
  you want it to survive backend restarts or scale to more replicas.
- Add Postgres if you want persistent chat history.
- Put Nginx or Caddy in front of port 8080 for TLS if this leaves your LAN.
- Add a language auto-detect step (fastText langid) so people don't have
  to pick their language manually each session.
