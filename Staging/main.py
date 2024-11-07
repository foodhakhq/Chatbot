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
    url = os.getenv("STAGING_OPENSEARCH_HOST")

    query = {
        "query": {
            "match": {
                "foodhak_user_id": foodhak_user_id
            }
        }
    }
    user = os.getenv("STAGING_OPENSEARCH_USER")
    password = os.getenv("STAGING_OPENSEARCH_PWD")
    
    response = requests.get(url, json=query, auth=HTTPBasicAuth(user, password))
    
    if response.status_code == 200:
        results = response.json()
        if results['hits']['total']['value'] > 0:
            result = results['hits']['hits'][0]['_source']
            user_health_goals = result.get("user_health_goals", [])
            primary_goal = next((goal for goal in user_health_goals if goal.get("user_goal", {}).get("is_primary")), None)
            
            # Fallback to the first goal if no primary goal is found
            primary_goal_title = primary_goal["user_goal"].get("title") if primary_goal else user_health_goals[0]["user_goal"].get("title")

            profile_info = {
                "User Name": result.get("name"),
                "User Age": result.get("age"),
                "User Sex": result.get("sex"),
                "Primary Goal Title": primary_goal_title, 
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

# Function to extract meal information dynamically
def extract_meal_info_dynamically(meal_recommendations):
    dynamic_info = {}
    for recommendation in meal_recommendations:
        item_name = recommendation.get('item')
        item_value = recommendation.get('value')
        item_unit = recommendation.get('unit')

        if item_name and item_value:
            item_name_lower = item_name.lower()
            if item_name_lower == "energy":
                formatted_name = "Energy (KCAL)"
            elif item_name_lower == "protein":
                formatted_name = "Protein (G)"
            elif item_name_lower == "fats":
                formatted_name = "Total Fat (G)"
            elif item_name_lower == "saturated fat":
                formatted_name = "Saturated Fat (G)"
            elif item_name_lower == "cholesterol":
                formatted_name = "Cholesterol (MG)"
            elif item_name_lower == "sodium":
                formatted_name = "Sodium Na (MG)"
            elif item_name_lower == "carbohydrate":
                formatted_name = "Total Carbohydrate (G)"
            elif item_name_lower == "dietary fibre":
                formatted_name = "Dietary Fiber (G)"
            elif item_name_lower == "vitamin c":
                formatted_name = "Vitamin C (MG)"
            elif item_name_lower == "calcium":
                formatted_name = "Calcium (MG)"
            elif item_name_lower == "iron":
                formatted_name = "Iron (MG)"
            elif item_name_lower == "potassium":
                formatted_name = "Potassium K (MG)"
            else:
                continue

            dynamic_info[formatted_name] = item_value

    return dynamic_info

# Function to get meal recommendations for a given FoodHak user ID
def get_meal_recommendations_for_user(foodhak_user_id):
    # Define the API endpoint and headers
    url = f"https://api-staging.foodhak.com/healthprofile-group-details/{foodhak_user_id}"
    headers = {
        "accept": "application/json",
        "Authorization": "Api-Key mS6WabEO.1Qj6ONyvNvHXkWdbWLFi9mLMgHFVV4m7",
        "X-CSRFToken": "K2JQAMgMyW91ofUU1nzGPKyGtMQu2F1K4tuJw6FdPuSf5Y2nBFussCcbFWAfhJi7"
    }

    # Send the GET request
    response = requests.get(url, headers=headers)

    # Check if the request was successful (status code 200 or 201)
    if response.status_code in [200, 201]:
        # Get the JSON response
        response_data = response.json()
        meal_recommendations = response_data.get("nutrition_values", [])
        return meal_recommendations
    else:
        # Print error details and return None if the request fails
        print(f"Failed to get data. Status code: {response.status_code}")
        print("Response text:", response.text)
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

def build_prompt(query, vec_results, conversation_history, users_name, users_age, users_sex, goal_title, ingredient_recommend, ingredient_avoid, dietary_restriction, allergens_type, primary_goal_title, dynamic_meal_info):
    #print("Ingredient Recommended:", ingredient_recommend)
    
    system_instruction = f"""
You are Foodhak Assistant, an authoritative yet friendly nutrition sidekick. Your mission is to provide personalized, evidence-based advice to help users make smart food and health choices.

Your goals:
- Offer accurate, up-to-date information based on both your extensive knowledge and the latest scientific research.
- Maintain a warm, conversational tone, engaging the user as if speaking with a friend.
- Personalize responses based on the user's profile provided.

**User Profile:**
- Name: {users_name}, Age: {users_age}, Sex: {users_sex}
- Primary Goal: {primary_goal_title}
- Goals: {goal_title}
- Preferences: {dietary_restriction}
- Allergies: {allergens_type}
- Recommended Ingredients: {ingredient_recommend}
- Ingredients to Avoid: {ingredient_avoid}
- Daily Nutritional Requirement of the User: {dynamic_meal_info}

- Use emojis sparingly to add warmth without detracting from professionalism.
- Empower {users_name} by making conversations enjoyable and informative, helping them make smart nutrition and health decisions.

**Formatting Guidelines for Responses:**
- Format your responses using HTML tags to improve readability.
  - Use `<p>` for each paragraph.
  - Use `<div>` to wrap each paragraph individually.
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

Utilize the user-profile information such as 
- Name: {users_name}, Age: {users_age}, Sex: {users_sex}
- Primary Goal: {primary_goal_title}
- Goals: {goal_title}
- Preferences: {dietary_restriction}
- Allergies: {allergens_type}
- Recommended Ingredients: {ingredient_recommend}
- Ingredients to Avoid: {ingredient_avoid}
- Daily Nutritional Requirement of the User: {dynamic_meal_info}, when relevant to the user's query. 

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
    primary_goal_title = user_profile.get("Primary Goal Title")
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

    #Include User Nutritional Information
    meal_recommendations = get_meal_recommendations_for_user(foodhak_user_id)
    dynamic_meal_info = extract_meal_info_dynamically(meal_recommendations)

    # Build Prompt
    prompt, system_instruction = build_prompt(query, vec_results, conversation_history, users_name, users_age, users_sex, goal_title, ingredient_recommend, ingredient_avoid, dietary_restriction, allergens_type, primary_goal_title, dynamic_meal_info)

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
        return claude_sonnet.generate_response_with_claude(models["claude"], prompt, system_instruction)

# This main function is now optional for standalone testing
if __name__ == "__main__":
    query = "Can you give me a recipe for masala dosa?"
    model_choice = "gemini"  # Change this as needed
    response = generate_response(query, model_choice)
    print("Final Response:", response.replace("*", " ").replace("  ", ""))
