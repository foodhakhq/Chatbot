from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Header, Depends
from fastapi.responses import JSONResponse
import os
import httpx
import json
import asyncio
from dotenv import load_dotenv
import uuid
import anthropic
from pydantic import BaseModel
from redis.asyncio.cluster import RedisCluster
from redis.cluster import ClusterNode
import logging
from openai import OpenAI


class StartSessionRequest(BaseModel):
    user_id: str
    user_name: str
    file_id: str = None  # Optional file_id for file processing


class EndSessionRequest(BaseModel):
    user_id: str


# Initialize logging
logging.basicConfig(level=logging.INFO)  # Replace DEBUG with INFO or WARNING
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# App Configuration
app = FastAPI()

API_KEY = os.getenv('STAGING_API_KEY')


def get_openai_client():
    api_key = os.getenv("STAGING_GROK_API_KEY")
    base_url = os.getenv("STAGING_GROK_URL")
    if not api_key:
        raise ValueError("STAGING_GROK_API_KEY not found in environment variables")
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    return client


redis_client = RedisCluster(
    startup_nodes=[ClusterNode("ai-test-cache-56sm92.serverless.euw2.cache.amazonaws.com", 6379)],
    decode_responses=True,
    socket_timeout=5,
    socket_connect_timeout=5,
    health_check_interval=30,
    max_connections=2000,
    ssl=True, )


async def safe_send_text(websocket: WebSocket, text_message: str) -> bool:
    try:
        await websocket.send_text(text_message)
    except WebSocketDisconnect:
        logger.warning("WebSocket disconnected while sending text.")
        return False
    except RuntimeError as e:
        logger.warning(f"Runtime error while sending text: {e}")
        return False
    return True


async def safe_send_json(websocket: WebSocket, data: dict) -> bool:
    try:
        await websocket.send_json(data)
    except WebSocketDisconnect:
        logger.warning("WebSocket disconnected while sending JSON.")
        return False
    except RuntimeError as e:
        logger.warning(f"Runtime error while sending JSON: {e}")
        return False
    return True


def initialize_claude_client():
    # Initialize the Anthropic client with the given location and project ID
    client = anthropic.Anthropic(
        api_key=os.getenv('ANTHROPIC_STAGING_API_KEY'),
    )
    return client


claude_client = initialize_claude_client()


async def validate_api_key(authorization: str = Header(...)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized API Key")
    token = authorization.split(" ")[1]
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized API Key")
    return token


# vector search call with an async version
async def perform_vector_search(query: str):
    url = "https://ai-foodhak.com/chromadb_vecstore"
    headers = {"Content-Type": "application/json"}
    data = {
        "queries": [query],  # Wrap the query string in a list
        "count": 10
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=data, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        return {}


async def generate_response_with_openai_streaming(client, prompt, system, websocket):
    """
    Streams reasoning_content, final content, and token-usage stats over a WebSocket.
    """
    try:
        message_id = None
        full_response = ""
        full_reasoning_response = ""
        # 1) Prepare the chat messages
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ]

        # 2) Kick off the streaming completion with usage included
        response = client.chat.completions.create(
            model="grok-3-mini-fast-beta",
            reasoning_effort="high",
            messages=messages,
            temperature=0.2,
            stream=True,
            stream_options={"include_usage": True}
        )

        # Flags to emit our headers exactly once
        printed_reasoning = False
        printed_content = False

        # 3) Iterate synchronously over each chunk
        for chunk in response:
            # 3a) If choices is empty, it’s the final usage-only packet
            if not getattr(chunk, "choices", None):
                usage = chunk.usage
                stats = (
                    f"\n\nNumber of completion tokens (input): "
                    f"{usage.completion_tokens}\n"
                    f"Number of reasoning tokens (input): "
                    f"{usage.completion_tokens_details.reasoning_tokens}"
                )
                await safe_send_text(websocket, json.dumps({
                    "type": "message_stop",
                    "message_id": message_id,
                    "data": stats
                }))
                break

            # 3b) Otherwise there’s exactly one choice with a delta
            choice = chunk.choices[0]
            delta = choice.delta

            if getattr(delta, "content", None):
                if not printed_content:
                    printed_content = True
                    await safe_send_text(websocket, json.dumps({
                        "message_id": message_id,
                        "type": "message_start",
                        "data": "\nFinal Response:"
                    }))
                await safe_send_text(websocket, json.dumps({
                    "message_id": message_id,
                    "type": "streaming",
                    "data": delta.content
                }))

            if message_id is None:
                message_id = chunk.id

        return full_response

    except Exception as e:
        logging.error(f"Error streaming response with OpenAI: {e}")
        # Send an error frame if the WS is still open
        try:
            await safe_send_text(websocket, json.dumps({
                "type": "error",
                "data": str(e)
            }))
        except:
            logging.warning("WebSocket closed before error could be sent")
        return ""


async def generate_response_with_claude_streaming(client, prompt, system_instruction, websocket):
    try:

        message_id = None
        response = client.messages.create(
            system=system_instruction,
            messages=[{"role": "user", "content": prompt}],
            model="claude-3-7-sonnet-20250219",
            temperature=0,
            max_tokens=7024,
            stream=True,
        )

        full_response = ""
        for chunk in response:
            if hasattr(chunk, 'type'):
                # Handle each chunk based on its type
                event_type = chunk.type

                if event_type == "message_start":
                    # Extract the message ID
                    message_id = chunk.message.id

                elif event_type == "content_block_delta" and hasattr(chunk.delta, 'text'):
                    # Stream each chunk of text with message ID
                    delta_text = chunk.delta.text
                    full_response += delta_text

                    sent_ok = await safe_send_text(websocket, json.dumps({
                        "message_id": message_id,
                        "type": "streaming",
                        "data": delta_text
                    }))
                    if not sent_ok:
                        break
                        # Allow other tasks to run
                    await asyncio.sleep(0)

                elif event_type == "message_stop":
                    # Send the final message_stop event

                    sent_ok = await safe_send_text(websocket, json.dumps({
                        "message_id": message_id,
                        "type": "message_stop",
                        "data": "Message stream completed."
                    }))
                    if not sent_ok:
                        break
        return full_response

    except Exception as e:
        logging.error(f"Error streaming response with Claude: {e}")

        sent_ok = await safe_send_text(websocket, json.dumps({
            "type": "error",
            "data": str(e)
        }))
        if not sent_ok:
            logger.warning("Attempted to send on a closed WebSocket")
        return ""


async def get_user_profile(foodhak_user_id):
    url = os.getenv('STAGING_OPENSEARCH_HOST')

    query = {
        "query": {
            "match": {
                "foodhak_user_id": foodhak_user_id
            }
        }
    }
    user = os.getenv('STAGING_OPENSEARCH_USER')
    password = os.getenv('STAGING_OPENSEARCH_PWD')

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=query, auth=(user, password))

    if response.status_code == 200:
        results = response.json()
        if results['hits']['total']['value'] > 0:
            result = results['hits']['hits'][0]['_source']

            user_health_goals = result.get("user_health_goals", [])
            primary_goal = next((goal for goal in user_health_goals if goal.get("user_goal", {}).get("is_primary")),
                                None)
            primary_goal_title = primary_goal["user_goal"].get("title") if primary_goal else (
                user_health_goals[0]["user_goal"].get("title") if user_health_goals else None
            )

            # Define nutrient formatting rules
            nutrient_mapping = {
                "energy": "Energy (KCAL)",
                "protein": "Protein (G)",
                "fats": "Total Fat (G)",
                "saturated fat": "Saturated Fat (G)",
                "cholesterol": "Cholesterol (MG)",
                "sodium": "Sodium Na (MG)",
                "carbohydrates": "Total Carbohydrate (G)",
                "dietary fibre": "Dietary Fiber (G)",
                "vitamin c": "Vitamin C (MG)",
                "calcium": "Calcium (MG)",
                "iron": "Iron (MG)",
                "potassium": "Potassium K (MG)",
                "hydration": "Hydration (ML)"
            }

            # Extract nutrients with proper formatting
            nutrients_data = result.get("nutrients", {}).get("results", {})
            formatted_nutrients = {}

            for nutrient_type_list in nutrients_data.values():
                for nutrient_type in nutrient_type_list:
                    item_name = nutrient_type.get("nutrition_guideline", {}).get("item", "").strip()
                    item_name_lower = item_name.lower()

                    # Check if the nutrient name is in the mapping
                    if item_name_lower in nutrient_mapping:
                        formatted_name = nutrient_mapping[item_name_lower]
                        formatted_nutrients[formatted_name] = str(nutrient_type.get("target_value"))

            profile_info = {
                "User Name": result.get("name"),
                "User Age": result.get("age"),
                "User Sex": result.get("sex"),
                "User Height": result.get("height"),
                "User Weight": result.get("weight"),
                "User Ethnicity": result.get("ethnicity", {}).get("title"),
                "Primary Goal Title": primary_goal_title,
                "Goal Titles": [
                    goal_sub["title"] for goal in result.get("user_health_goals", [])
                    for key in ["user_goal", "user_goals"] if key in goal
                    for goal_sub in (goal[key] if isinstance(goal[key], list) else [goal[key]])
                ],
                "Ingredients to Recommend": [
                    {
                        "common_name": ingredient.get("common_name"),
                        "first_relationship_extract": ingredient["relationships"][0]["extracts"] if ingredient[
                            "relationships"] else None,
                        "first_relationship_url": ingredient["relationships"][0]["url"] if ingredient[
                            "relationships"] else None
                    }
                    for goal in result.get("user_health_goals", [])
                    for ingredient in goal.get("ingredients_to_recommend", [])
                ],
                "Ingredients to Avoid": [
                    {
                        "common_name": ingredient.get("common_name"),
                        "first_relationship_extract": ingredient["relationships"][0]["extracts"] if ingredient[
                            "relationships"] else None,
                        "first_relationship_url": ingredient["relationships"][0]["url"] if ingredient[
                            "relationships"] else None
                    }
                    for goal in result.get("user_health_goals", [])
                    for ingredient in goal.get("ingredients_to_avoid", [])
                ],
                "Dietary Restriction Name": result.get("dietary_restrictions", {}).get("name"),
                "Allergens Types": [
                    allergen.get("type")
                    for allergen in result.get("allergens", [])
                ],
                "Daily Nutritional Requirement": formatted_nutrients
            }
            return profile_info
        else:
            logger.error("No matching user profile found.")
            return None
    else:
        logger.error(f"Error in get_user_profile: {response.status_code} - {response.text}")
        return None


def build_prompt(query, vec_results, conversation_history, users_name, users_age, users_sex, users_height, users_weight, users_ethnicity, goal_title,
                 ingredient_recommend, ingredient_avoid, dietary_restriction, allergens_type, primary_goal_title,
                 daily_nutritional_requirement):
    # print("Ingredient Recommended:", ingredient_recommend)

    system_instruction = f"""
You are **Faye**, Foodhak's authoritative yet approachable nutrition side-kick.  
Your mission is to deliver precise, evidence-based food and health guidance, personalised to each user's needs, in a calm, concise, and genuinely helpful tone.

────────────────────────────────────────────
1. Conversational Style
────────────────────────────────────────────
• Warm-but-measured greeting – greet the user **once per session** (e.g. "Hi {users_name}—") and never repeat it.  
• Tone – friendly, supportive, professional; no excess exclamation marks or slang.  
• Brevity – for simple queries, reply in one short paragraph unless more detail is clearly useful.  
• Emojis – maximum **one** per answer, only if it adds warmth or clarity.

────────────────────────────────────────────
2. Personalisation Inputs
────────────────────────────────────────────
Name: {users_name} Age: {users_age} Sex: {users_sex}  
Height: {users_height} Weight: {users_weight} Ethnicity: {users_ethnicity}

Primary Goal: {primary_goal_title}  
Other Goals:  {goal_title}

Dietary Preferences/Restrictions: {dietary_restriction}  
Allergies: {allergens_type}

Recommended Ingredients: {ingredient_recommend}  
Ingredients to Avoid:   {ingredient_avoid}

Daily Nutrient Targets: {daily_nutritional_requirement}

────────────────────────────────────────────
3. Content Rules
────────────────────────────────────────────
1. Evidence focus – combine broad nutrition knowledge with latest science.  
2. **No unsolicited alternatives** – suggest substitutes only on request **or** if a chosen food conflicts with allergies/goals.  
3. Immediate fulfilment – if the user accepts an offer (e.g. wants a recipe), provide it at once; avoid "fetching" language.  
4. Ask follow-up questions only when essential.  
5. Internal query classification (`general` vs `Foodhak-db`, never reveal).  
   • If `Foodhak-db`, integrate {vec_results} (excluding recipes) and append:  
     `<br/>This answer is verified by Foodhak.`

────────────────────────────────────────────
4. HTML Formatting Guide
────────────────────────────────────────────
Wrap every answer in minimal, valid HTML:

<div>
  <p>…paragraph…</p>
  <p>…paragraph…</p>
  <ul>
    <li>…bullet…</li>
    <li>…bullet…</li>
  </ul>
</div>

Use `<strong>` or `<em>` sparingly; use `<h2>` for clear section headings; close all tags.

────────────────────────────────────────────
5. Conversation-Flow Logic (internal)
────────────────────────────────────────────
IF first message in thread AND greeting not yet used → greet {users_name} once  
ELSE → continue without any additional greeting

────────────────────────────────────────────
6. Response Checklist (internal, silent)
────────────────────────────────────────────
□ Personal data applied where relevant  
□ Scientific accuracy checked  
□ No repeat greeting / no excess enthusiasm  
□ No unsolicited alternatives  
□ HTML valid & tidy  
□ Added Foodhak verification line if {vec_results} used  

Be the most trusted nutrition ally—succinct, evidence-driven, and always user-centric.
"""

    prompt = f"""
**Current Query:** "{query}"

**Conversation History:** {conversation_history}

**Vector Results:** {vec_results}

<<Generate final HTML-formatted reply here, following the System Prompt rules>>
"""
    return prompt, system_instruction

async def generate_response(query, session_key, foodhak_user_id, websocket=None):
    # Retrieve conversation history from Redis (synchronously)
    conversation_history = await async_get_conversation_history(session_key)
    user_profile = await get_user_profile(foodhak_user_id)
    if not user_profile:
        return "Error: User profile not found."

    # Extract user details from the profile
    users_name = user_profile.get("User Name")
    users_age = user_profile.get("User Age")
    users_sex = user_profile.get("User Sex")
    users_height = user_profile.get("User Height")
    users_weight = user_profile.get("User Weight")
    users_ethnicity = user_profile.get("User Ethnicity")
    primary_goal_title = user_profile.get("Primary Goal Title")
    goal_title = user_profile.get("Goal Titles")
    ingredient_recommend = user_profile.get("Ingredients to Recommend")
    ingredient_avoid = user_profile.get("Ingredients to Avoid")
    dietary_restriction = user_profile.get("Dietary Restriction Name")
    allergens_type = user_profile.get("Allergens Types")

    # Perform vector search and join the results
    vec_results = await perform_vector_search(query)

    # Include additional nutritional information
    daily_nutritional_requirement = user_profile.get("Daily Nutritional Requirement")

    # Build prompt and system instruction using your helper
    prompt, system_instruction = build_prompt(
        query, vec_results, conversation_history,
        users_name, users_age, users_sex, users_height, users_weight, users_ethnicity,
        goal_title, ingredient_recommend, ingredient_avoid,
        dietary_restriction, allergens_type,
        primary_goal_title, daily_nutritional_requirement
    )

    try:
        if websocket:
            logging.info("Attempting response generation with Claude-Sonnet-3.7...")
            # Directly await the streaming response from Anthropic Claude
            return await generate_response_with_claude_streaming(
                        claude_client,
                        prompt,
                        system_instruction,
                        websocket
                    )
        else:
            # If no websocket is provided, you can implement a non-streaming fallback
            return "Non-websocket response generation not implemented."
    except Exception as anthropic_error:
        # Log the error to see what args look like
        logging.error(f"Anthropic error args: {anthropic_error.args}")
        error_data = anthropic_error.args[0] if anthropic_error.args else {}

        # If error_data is not a dict, try to parse it as JSON
        if not isinstance(error_data, dict):
            try:
                error_data = json.loads(error_data)
            except Exception:
                error_data = {}

        # Also check the error message string as a fallback
        error_str = str(anthropic_error)

        if error_data.get("error", {}).get("type") == "overloaded_error" or "overloaded_error" in error_str:
            logging.warning("Claude-sonnet-3.7 is overloaded. Falling back to Grok...")
            try:
                openai_client = get_openai_client()
                if websocket:
                    logging.info("Using Grok-3 streaming response generation...")
                    return await generate_response_with_openai_streaming(
                openai_client,
                prompt,
                system_instruction,
                websocket
            )
                else:
                    return "Non-websocket fallback response not implemented."
            except Exception as e:
                logging.error("OpenAI is also overloaded.")
                error_message = "Both services are currently experiencing high demand. Please try again in a few minutes."
                if websocket:
                    logging.info("Sending error through websocket.")
                    await safe_send_text(websocket, json.dumps({
                        "type": "error",
                        "data": str(e)
                    }))
                    return error_message
                else:
                    logging.error(f"Unexpected error : {e}")
                    return "Unexpected error during response generation."
        else:
            logging.error(f"Anthropic API error: {anthropic_error}")
            return "Error generating response from Anthropic API."
    except Exception as e:
        logging.error(f"Unexpected error during response generation: {e}")
        return "Unexpected error during response generation."


async def get_or_create_session(user_id: str, user_name: str):
    base_session_key = f"user:{user_id}"
    session_id = await redis_client.hget(base_session_key, "session_id")
    if session_id:
        full_session_key = f"{base_session_key}:{session_id}"
        conversation_history_str = await redis_client.hget(full_session_key, "conversation_history")
        try:
            conversation_history = json.loads(conversation_history_str) if conversation_history_str else []
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing conversation history: {e}")
            conversation_history = []
    else:
        session_id = str(uuid.uuid4())
        full_session_key = f"{base_session_key}:{session_id}"
        conversation_history = []
        await redis_client.hset(base_session_key, mapping={"session_id": session_id})
        await redis_client.hset(full_session_key, mapping={
            "user_id": user_id,
            "user_name": user_name,
            "session_id": session_id,
            "conversation_history": json.dumps(conversation_history),
        })
        # Set TTL for the session key (e.g., 24 hours)
        await redis_client.expire(full_session_key, 86400)
    return full_session_key, conversation_history


async def async_update_session_with_distributed_lock(session_key: str, user_input: str, model_response: str):
    lock_key = f"lock:{session_key}"
    for attempt in range(3):  # Try 3 times
        lock = redis_client.lock(lock_key, timeout=2, sleep=0.1 * (2 ** attempt))
        acquired = await lock.acquire(blocking=True, blocking_timeout=1)
        if acquired:
            try:
                conversation_history_str = await redis_client.hget(session_key, "conversation_history")
                try:
                    conversation_history = json.loads(conversation_history_str) if conversation_history_str else []
                except json.JSONDecodeError:
                    logger.error("Error parsing conversation history.")
                    conversation_history = []
                conversation_history.extend([
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": model_response},
                ])
                await redis_client.hset(session_key, "conversation_history", json.dumps(conversation_history))
                logger.info(f"Session {session_key} updated successfully with distributed lock.")
                return  # Success
            finally:
                await lock.release()
        await asyncio.sleep(0.2 * (2 ** attempt))
    logger.error("Failed to acquire lock after multiple attempts")
    raise Exception("Session update failed due to lock contention")


async def async_get_conversation_history(session_key: str):
    conversation_history_str = await redis_client.hget(session_key, "conversation_history")
    try:
        return json.loads(conversation_history_str) if conversation_history_str else []
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing conversation history: {e}")
        return []


class ConnectionManager:
    def __init__(self):
        self.active_connections = {}
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        async with self.lock:
            self.active_connections[user_id] = websocket

    async def disconnect(self, user_id: str):
        async with self.lock:
            self.active_connections.pop(user_id, None)

    async def send_message(self, user_id: str, message: dict):
        async with self.lock:
            websocket = self.active_connections.get(user_id)
        if websocket:
            # Use safe_send_json directly, to ensure we handle a closed socket.
            sent_ok = await safe_send_json(websocket, message)
            if not sent_ok:
                logger.warning(f"WebSocket for user_id {user_id} is closed; message not delivered.")
                # Decide whether to return, log only, or do something else.
                return


manager = ConnectionManager()


@app.post("/chat/start_session")
async def start_session(
        request: StartSessionRequest,
        token: str = Depends(validate_api_key)  # API key is now validated here
):
    try:
        user_id = request.user_id
        user_name = request.user_name

        # Get or create session
        session_key, conversation_history = await get_or_create_session(user_id, user_name)

        return {
            "session_key": session_key,
            "user_id": user_id,
            "user_name": user_name,
            "status": "Session started successfully",
            "conversation_history": conversation_history,
            "websocket_url": f"wss://staging.ai-foodhak.com/ws/{user_id}"
        }
    except Exception as e:
        logging.error(f"Error in start_session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(websocket, user_id)
    try:
        # Retrieve or create the session
        session_key, _ = await get_or_create_session(user_id, "WebSocket User")

        while True:
            # Receive message from the client (all messages are treated as plain text)
            raw_message = await websocket.receive_text()
            user_input = raw_message

            logger.info(f"Processed message - user_id: {user_id}, user_input: {user_input}")

            try:
                # Process the text message
                response = await generate_response(user_input, session_key, user_id, websocket)
                # Update session with the conversation
                await async_update_session_with_distributed_lock(session_key, user_input, response)

            except Exception as e:
                logger.error(f"Error processing message for user_id: {user_id} - {e}")
                sent_ok = await safe_send_text(websocket, json.dumps({
                    "type": "error",
                    "data": str(e)
                }))
                if not sent_ok:
                    logger.warning("Attempted to send on a closed WebSocket")
                break

    except WebSocketDisconnect:
        await manager.disconnect(user_id)
        logger.info(f"WebSocket disconnected for user_id: {user_id}")
    except Exception as e:
        logger.error(f"Unexpected error in WebSocket for user_id: {user_id} - {e}")
        sent_ok = await safe_send_text(websocket, json.dumps({
            "type": "error",
            "data": "Connection error. Please refresh and try again."
        }))
        if not sent_ok:
            logger.warning("Attempted to send on a closed WebSocket")
        await websocket.close()


@app.post("/chat/end_session")
async def end_session(request: EndSessionRequest):
    user_id = request.user_id
    try:
        session_key = f"user:{user_id}"
        if await redis_client.exists(session_key):
            session_id = await redis_client.hget(session_key, "session_id")
            if session_id:
                full_session_key = f"{session_key}:{session_id}"
                await redis_client.delete(full_session_key)
            await redis_client.delete(session_key)
            return {"message": "Session ended successfully"}
        return JSONResponse(content={"error": "No active session found"}, status_code=404)
    except Exception as e:
        logger.error(f"Unexpected error in end_session: {e}")
        return JSONResponse(content={"error": "Internal Server Error"}, status_code=500)


@app.get("/")
async def home():
    return {"message": "Chatbot FastAPI server is running!"}


@app.get("/health")
async def health_check():
    try:
        print("In chatbot Health check")
        await redis_client.ping()
        return {"status": "healthy", "redis": "connected"}
    except Exception as e:
        return JSONResponse(content={"status": "unhealthy", "error": str(e)}, status_code=503)


if __name__ == '__main__':
    import uvicorn
    import os

    # Get port from environment variable or default to 8080
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)