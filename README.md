````markdown
# Foodhak Chatbot AI Service

A conversational, real-time nutrition assistant for Foodhak users—personalized, evidence-based, and session-aware.

---

## 🌍 Environments

- **Production** API: `https://ai-foodhak.com`
- **Staging** API: `https://staging.ai-foodhak.com`

---

## 🚦 How It Works

1. **Start a Session:**  
   - Client POSTs to `/chat/start_session` with user info.
   - Receives a unique `session_key` and `websocket_url`.
2. **Chat via WebSocket:**  
   - Connect to `websocket_url`.
   - Send plain text messages for conversational nutrition Q&A.
   - Receive real-time, streaming JSON responses.
3. **End a Session:**  
   - POST to `/chat/end_session` to clean up the session.

All requests must include an **Authorization** header:  
`Authorization: Bearer <API_KEY>`

---

## 🛠️ API Usage

### 1. Start a Chat Session

#### Production

```bash
curl -X POST https://ai-foodhak.com/chat/start_session \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "USER123", "user_name": "Alex"}'
````

**Response:**

```json
{
  "session_key": "user:USER123:abcdef-1234-uuid",
  "user_id": "USER123",
  "user_name": "Alex",
  "status": "Session started successfully",
  "conversation_history": [],
  "websocket_url": "wss://ai-foodhak.com/ws/USER123"
}
```

---

### 2. Real-Time Chat (WebSocket)

Connect to the `websocket_url` provided.

* **Send:** Plain text messages (e.g. `"Can I eat peanuts with my profile?"`)
* **Receive:** Streaming JSON messages

  * Type: `message_start`, `streaming`, `message_stop`, or `error`

**Example using Python:**

```python
import websockets
import asyncio

async def chat():
    uri = "wss://ai-foodhak.com/ws/USER123"
    async with websockets.connect(uri) as ws:
        await ws.send("Are almonds okay for my cholesterol?")
        async for msg in ws:
            print(msg)

asyncio.run(chat())
```

---

### 3. End a Session

```bash
curl -X POST https://ai-foodhak.com/chat/end_session \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "USER123"}'
```

**Success:**

```json
{ "message": "Session ended successfully" }
```

---

### 4. Health Check

```bash
curl https://ai-foodhak.com/health
```

**Success:**

```json
{
  "status": "healthy",
  "redis": "connected"
}
```

---

## 📦 Endpoints

| Method | Endpoint              | Purpose                                  |
| ------ | --------------------- | ---------------------------------------- |
| POST   | `/chat/start_session` | Start a chat session (get WebSocket URL) |
| WS     | `/ws/{user_id}`       | Real-time chat WebSocket                 |
| POST   | `/chat/end_session`   | End/clean up a chat session              |
| GET    | `/health`             | Health check                             |
| GET    | `/`                   | Welcome message                          |

---

## 🔒 Security

* All endpoints require `Authorization: Bearer <API_KEY>`.
* Never share your API key.
* Session and chat data is managed with Redis Cluster.

---

## 📝 Notes

* Powered by Claude 3 and OpenAI Grok, with seamless fallback logic.
* Replies are concise, HTML-formatted, and tailored to your Foodhak profile.
* Vector store and user profile are queried automatically.
* Rate limits and overloads are handled gracefully with informative errors.

---

## 📣 For developers

* See `main.py` for full implementation.
* Environment variables required:
  `API_KEY`, `ANTHROPIC_PRODUCTION_API_KEY`, `PRODUCTION_GROK_API_KEY`, `PRODUCTION_GROK_URL`, `OPENSEARCH_HOST`, `OPENSEARCH_USER`, `OPENSEARCH_PWD`, etc.

---
