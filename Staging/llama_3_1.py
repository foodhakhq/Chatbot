import openai
from google.auth import default
from google.auth.transport.requests import Request

# Define the location for the Llama model (only 'us-central1' is supported)
MODEL_LOCATION = "us-central1"

# Initialize Llama 3.1 model using Google Application Default Credentials (ADC)
def initialize_llama_model(project_id, location):
    # Get the credentials from the current environment (Google Cloud, App Engine, etc.)
    credentials, _ = default()

    # Refresh the credentials to get a valid access token
    auth_request = Request()
    credentials.refresh(auth_request)

    # Define the model endpoint URL (Llama 3.1 using Vertex AI Model-as-a-Service)
    MODEL_ENDPOINT = f"https://{location}-aiplatform.googleapis.com/v1beta1/projects/{project_id}/locations/{location}/endpoints/openapi/chat/completions?"

    # Configure the OpenAI SDK to point to the Llama 3.1 API endpoint using the access token
    client = openai.OpenAI(
        base_url=MODEL_ENDPOINT,
        api_key=credentials.token,  # Use the access token as the API key
    )

    # Return the client and the model ID for further use
    MODEL_ID = "meta/llama3-405b-instruct-maas"
    return client, MODEL_ID

# Generate a response from the Llama 3.1 model using Vertex AI MaaS
def generate_response_with_llama(client, model_id, prompt, temperature=0, max_tokens=1024, top_p=1.0, stream=True):
    response = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        stream=stream,
    )

    final_response = ""
    if stream:
        for chunk in response:
            content_part = chunk.choices[0].delta.content
            
            # Format the content_part before printing and appending
            formatted_content = format_response(content_part)
            
            print(formatted_content, end="", flush=True)
            final_response += formatted_content
    else:
        final_response = response.choices[0].message.content
        final_response = format_response(final_response)

    return final_response.strip()

# A function to format the response content
def format_response(content):
    # Perform any formatting needed, e.g., ensuring proper line breaks or correcting spacing
    content = content.replace('\\n', '\n')  # Handle any newline characters
    content = content.replace('* ', '\n* ') # Ensure bullet points are on new lines
    content = content.strip()  # Remove any leading or trailing whitespace
    
    # Add additional formatting as needed
    return content
