import vertexai
from google.cloud import aiplatform
from langchain_google_vertexai import VertexAIEmbeddings, VectorSearchVectorStore
import gemini_flash
import mistral_large
import llama_3_1
import claude_sonnet
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
import os
# Set your project details
PROJECT_ID = "central-muse-388319"
REGION = "us-central1"
BUCKET = "chatbot-relationships"
DISPLAY_NAME = "4661872127165595648"
DEPLOYED_INDEX_ID = "5511996925575954432"
LOCATION_CLAUDE = "europe-west1"


# Load environment variables from the .env file
load_dotenv()

# Initialize the Vertex AI SDK
aiplatform.init(project=PROJECT_ID, location=REGION, staging_bucket=f"gs://{BUCKET}")

# Initialize the embedding model
embedding_model = VertexAIEmbeddings(model_name="text-embedding-004")


def get_user_profile(foodhak_user_id):
    url = os.getenv("OPENSEARCH_HOST")

    query = {
        "query": {
            "match": {
                "foodhak_user_id": foodhak_user_id
            }
        }
    }
    user = os.getenv("OPENSEARCH_USER")
    password = os.getenv("OPENSEARCH_PWD")
    
    response = requests.get(url, json=query, auth=HTTPBasicAuth(user, password))
    
    if response.status_code == 200:
        results = response.json()
        if results['hits']['total']['value'] > 0:
            result = results['hits']['hits'][0]['_source']
            
            profile_info = {
                "User Name": result.get("name"),
                "User Age": result.get("age"),
                "User Sex": result.get("sex"),
                "Goal Titles": [
                    goal_sub["title"] for goal in result.get("user_health_goals", [])
                    for key in ["user_goal", "user_goals"] if key in goal
                    for goal_sub in (goal[key] if isinstance(goal[key], list) else [goal[key]])
                ],
                "Ingredients to Recommend": [
                    {
                        "common_name": ingredient.get("common_name"),
                        "first_relationship_extract": ingredient["relationships"][0]["extracts"] if ingredient["relationships"] else None,
                        "first_relationship_url": ingredient["relationships"][0]["url"] if ingredient["relationships"] else None
                    }
                    for goal in result.get("user_health_goals", [])
                    for ingredient in goal.get("ingredients_to_recommend", [])
                ],
                "Ingredients to Avoid": [
                    {
                        "common_name": ingredient.get("common_name"),
                        "first_relationship_extract": ingredient["relationships"][0]["extracts"] if ingredient["relationships"] else None,
                        "first_relationship_url": ingredient["relationships"][0]["url"] if ingredient["relationships"] else None
                    }
                    for goal in result.get("user_health_goals", [])
                    for ingredient in goal.get("ingredients_to_avoid", [])
                ],
                "Dietary Restriction Name": result.get("dietary_restrictions", {}).get("name"),
                "Allergens Types": [
                    allergen.get("type") 
                    for allergen in result.get("allergens", [])
                ]
            }
            return profile_info
        else:
            print("No matching user profile found.")
            return None
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return None



# Vector Search Setup
vector_store = VectorSearchVectorStore.from_components(
    project_id=PROJECT_ID,
    region=REGION,
    gcs_bucket_name=BUCKET,
    index_id=aiplatform.MatchingEngineIndex(DISPLAY_NAME).name,
    endpoint_id=aiplatform.MatchingEngineIndexEndpoint(DEPLOYED_INDEX_ID).name,
    embedding=embedding_model,
    stream_update=True,
)

def build_prompt(query, vec_results, conversation_history, users_name, users_age, users_sex, goal_title, ingredient_recommend, ingredient_avoid, dietary_restriction, allergens_type):
    #print("Ingredient Recommended:", ingredient_recommend)
    
    system_instruction = f"""
You are Foodhak Assistant, an authoritative yet friendly nutrition sidekick. Your mission is to provide personalized, evidence-based advice to help users make smart food and health choices.

Your goals:
- Offer accurate, up-to-date information based on both your extensive knowledge and the latest scientific research.
- Maintain a warm, conversational tone, engaging the user as if speaking with a friend.
- Personalize responses based on the user's profile provided.

**User Profile:**
- Name: {users_name}, Age: {users_age}, Sex: {users_sex}
- Goals: {goal_title}
- Preferences: {dietary_restriction}
- Allergies: {allergens_type}
- Recommended Ingredients: {ingredient_recommend}
- Ingredients to Avoid: {ingredient_avoid}

- Use emojis sparingly to add warmth without detracting from professionalism.
- Empower {users_name} by making conversations enjoyable and informative, helping them make smart nutrition and health decisions.

**Formatting Guidelines for Responses:**
- Format your responses using HTML tags to improve readability.
  - Use `<p>` for paragraphs.
  - Use `<ul>` and `<li>` for bullet points.
  - Use `<strong>` or `<em>` for emphasis.
  - Use `<h1>`, `<h2>` for headings.
  - Use line breaks (`<br>`) to separate different sections if necessary.
- Ensure the HTML is properly closed and nested.

**Important Instructions:**
- Always use the conversation history to understand the context and answer follow-up questions appropriately.
- Before responding, check the conversation history:
    - If this is the first message or if you have not greeted {users_name} yet, start by greeting them by name to increase warmth.
    - If you have already greeted {users_name}, continue the conversation naturally without additional greetings.
- **When you offer to provide something (e.g., a recipe) and the user agrees, immediately provide the content using your own knowledge, without any delays.**
- **Avoid statements like "I'll fetch that for you" or "Let me get that." Instead, proceed to deliver the requested information directly.**
- Use your own extensive knowledge to provide recipes.
- Only ask follow-up questions if you are confident that you can provide accurate and helpful answers based on the user's potential responses.
- Focus on providing valuable advice based on the user's provided profile and known preferences.
- Classify the user's query into either 'general' or 'Foodhak database-related' internally (do not reveal the classification to the user).
  - When classifying, consider if the user is responding to a previous question.
- For 'Foodhak database-related' queries, utilize the data in `{vec_results}` (excluding recipes) and conclude responses with "<br/>This answer is verified by Foodhak."
- For other queries, including requests for recipes, feel free to draw upon your own knowledge to provide comprehensive answers.

Your goal is to be the <strong>best nutrition assistant</strong>, delivering accurate, personalized advice seamlessly while empowering {users_name} to make informed decisions.
"""



    prompt = f"""
**Current Query:** "{query}"

The user's current input may be a response to a previous question you asked. Use the conversation history to determine the context and provide an appropriate answer.

**When the user agrees to receive specific information, such as a recipe, provide it immediately and directly using your own knowledge, without any additional confirmation or delay.**

Utilize the data in `{vec_results}`, which contains scientific research about certain foods, diets, nutrition, etc., when relevant to the user's query (excluding recipes).

Use the conversation history: `{conversation_history}` to provide a relevant and context-aware answer.

Remember to keep the tone friendly and conversational, engaging {users_name} with personalized insights.
"""
    return prompt, system_instruction

def initialize_models(system_instruction):
    # Initialize models using credentials
    gemini_model_instance = gemini_flash.initialize_gemini_model(PROJECT_ID, REGION, system_instruction)
    llama_client, llama_model_id = llama_3_1.initialize_llama_model(PROJECT_ID, REGION)
    claude_client = claude_sonnet.initialize_claude_client(PROJECT_ID, LOCATION_CLAUDE)
    
    return {
        "gemini": gemini_model_instance,
        "llama": (llama_client, llama_model_id),
        "claude": claude_client
    }

def generate_response(query, model_choice, session_key, r, foodhak_user_id):

    user_profile = get_user_profile(foodhak_user_id)
    
    if not user_profile:
        return "Error: User profile not found."

    users_name = user_profile.get("User Name")
    users_age = user_profile.get("User Age")
    users_sex = user_profile.get("User Sex")
    goal_title = user_profile.get("Goal Titles") 
    ingredient_recommend = user_profile.get("Ingredients to Recommend")
    ingredient_avoid = user_profile.get("Ingredients to Avoid")
    dietary_restriction = user_profile.get("Dietary Restriction Name")
    allergens_type = user_profile.get("Allergens Types")

    conversation_history = r.hget(session_key, "conversation_history").decode('utf-8')
    print("Conversation History", conversation_history)
    # Perform Vector Search
    results = vector_store.similarity_search(query, k=5)
    vec_results = "\n".join(result.page_content for result in results)

    # Build Prompt
    prompt, system_instruction = build_prompt(query, vec_results, conversation_history, users_name, users_age, users_sex, goal_title, ingredient_recommend, ingredient_avoid, dietary_restriction, allergens_type)

    # Initialize Models
    models = initialize_models(system_instruction)

    if model_choice == "gemini":
        return gemini_flash.generate_response_with_gemini(models["gemini"], prompt)
    elif model_choice == "mistral":
        return mistral_large.generate_response_with_mistral(prompt)
    elif model_choice == "llama":
        llama_client, llama_model_id = models["llama"]
        return llama_3_1.generate_response_with_llama(llama_client, llama_model_id, prompt)
    elif model_choice == "claude":
        return claude_sonnet.generate_response_with_claude(models["claude"], prompt)

# This main function is now optional for standalone testing
if __name__ == "__main__":
    query = "Can you give me a recipe for masala dosa?"
    model_choice = "gemini"  # Change this as needed
    response = generate_response(query, model_choice)
    print("Final Response:", response.replace("*", " ").replace("  ", ""))