```markdown
# Chatbot

## Overview

This documentation outlines the process of starting and ending a session with a chatbot built using advanced Language Learning Models (LLMs). The chatbot has been deployed on a Google Cloud Platform (GCP) Virtual Machine (VM) instance using a Flask server. It is built on top of the Relhak dataset and leverages the Retrieval-Augmented Generation (RAG) approach from Vertex AI vector search. Embeddings are generated using the `text-embedding-004` model from Google.

The chatbot uses a session management tool called Redis, which stores user names and conversations in memory. This API allows for session management through two endpoints: `start_session` and `end_session`. The chatbot does not have a frontend, and all interactions are managed through these endpoints.

## Endpoints

### 1. Start Session - Chatbot

This endpoint initializes a session for the chatbot by storing the user ID and the initial message in Redis. This allows the chatbot to maintain context across multiple interactions with the user.

**Endpoint URL:**

`https://www.foodhakai.com/chat/start_session`

**HTTP Method:**

`POST`

**Headers:**

- `Content-Type: application/json`
- `Authorization: Bearer test123`

**Request Payload:**

```json
{
  "user_id": "user123",
  "user_name": "Abishek",
  "message": "I’m diabetic, 60 years old, I love to eat sweets, I weigh over 100 kgs."
}
```

**Parameters:**

- `user_id`: A unique identifier for the user. This is required to track and manage the user's session.
- `user_name`: The name of the user initiating the session.
- `message`: The initial message from the user, which will be used to start the conversation with the chatbot.

**Description:**

When this endpoint is called, it creates a new session in Redis by storing the `user_id` and the associated conversation history. The chatbot, which is powered by LLMs such as Gemini-Flash, Claude-3.5-Sonnet, Mistral-Large, and Llama-3.1, will use this data to personalize its responses and maintain context throughout the session.

### 2. End Session - Chatbot

This endpoint terminates the session for a given user by deleting their session data from Redis.

**Endpoint URL:**

`https://www.foodhakai.com/chat/end_session`

**HTTP Method:**

`POST`

**Headers:**

- `Content-Type: application/json`
- `Authorization: Bearer test123`

**Request Payload:**

```json
{
  "user_id": "user123"
}
```

**Parameters:**

- `user_id`: The unique identifier of the user whose session is to be terminated.

**Description:**

When this endpoint is called, it removes the session associated with the provided `user_id` from Redis. This effectively ends the conversation, and all the data stored in memory for this session is deleted.

## Technical Details

- **Deployment**: The chatbot is deployed on a GCP VM instance on port 5000 using Flask.
- **Models**: The chatbot is powered by several advanced LLMs, including Gemini-Flash, Claude-3.5-Sonnet, Mistral-Large, and Llama-3.1.
- **Session Management**: Redis is used for session management, storing user names and conversation history in memory.
- **Dataset**: The chatbot is built on the Relhak dataset, using the Retrieval-Augmented Generation (RAG) approach.
- **Embedding Generation**: Embeddings for vector search are generated using Google’s `text-embedding-004` model.

## Example Usage

### Staging-Start Session

```bash
curl -X POST https://www.staging-foodhakai.com/chat2/start_session \
-H "Content-Type: application/json" \
-H "Authorization: Bearer mS6WabEO.1Qj6ONyvNvHXkWdbWLFi9mLMgHFVV4m7" \
-d '{
  "user_id": "0df5911b-b28c-49e4-b574-f9e8acadf7a6",
  "user_name": "Abishek",
  "message": "Hi Hello"
}'
```

### Staging-End Session

```bash
curl -X POST https://www.staging-foodhakai.com/chat2/end_session \
-H "Content-Type: application/json" \
-H "Authorization: Bearer mS6WabEO.1Qj6ONyvNvHXkWdbWLFi9mLMgHFVV4m7" \
-d '{
  "user_id": "0c4f9f04-0ff6-40e7-8726-3394575c8092"
}'
```

### **Production-Start Session**

```bash
curl -X POST https://www.foodhakai.com/chat/start_session \
-H "Content-Type: application/json" \
-H "Authorization: Bearer viJ8u142.NaQl7JEW5u8bEJpqnnRuvilTfDbHyWty" \
-d '{
  "user_id": "9acc25b6-b238-407e-bc85-44d723bf4551",
  "user_name": "penny bodle",
  "message": "Hi Hello"
}'
```

### Production-End Session

```bash
curl -X POST https://www.foodhakai.com/chat/end_session \
-H "Content-Type: application/json" \
-H "Authorization: Bearer viJ8u142.NaQl7JEW5u8bEJpqnnRuvilTfDbHyWty" \
-d '{
  "user_id": "9acc25b6-b238-407e-bc85-44d723bf4551"
}'
```

## Conclusion

This API documentation provides a comprehensive guide to using the chatbot’s session management system. By following the instructions outlined above, users can initiate and terminate sessions with the chatbot, allowing for a personalized and context-aware interaction. The chatbot leverages cutting-edge LLM technology and efficient session management through Redis to deliver an optimized user experience.
```
This format provides all necessary details to understand how the endpoints function, how to interact with them, and how to configure and use the chatbot API effectively.
