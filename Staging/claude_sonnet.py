import tiktoken
from anthropic import AnthropicVertex

class HTTPException(Exception):
    """Base exception for HTTP errors."""
    def __init__(self, status_code, message):
        self.status_code = status_code
        self.message = message
        super().__init__(self.message)

class SessionLimitReachedException(HTTPException):
    """Custom exception for HTTP 413 - Session Limit Reached."""
    def __init__(self, token_count, limit=150000):
        super().__init__(413, f"HTTP Status Code 413 - Session Limit Reached: Token count is {token_count}, exceeding the limit of {limit} tokens.")
        self.token_count = token_count
        self.limit = limit

def count_tokens_tiktoken(text, model_name="gpt-3.5-turbo"):
    # Use tiktoken to get the appropriate tokenizer for the model
    tokenizer = tiktoken.encoding_for_model(model_name)
    tokens = tokenizer.encode(text)
    return len(tokens)

def initialize_claude_client(project_id, location):
    # Initialize the Anthropic client with the given location and project ID
    client = AnthropicVertex(region=location, project_id=project_id)
    return client

def generate_response_with_claude(client, prompt, system, model="claude-3-5-sonnet@20240620", max_tokens=1024, stream=True):
    # Calculate the number of tokens in the prompt using tiktoken
    token_count = count_tokens_tiktoken(prompt)

    # Check if the token count exceeds 50 for testing
    if token_count > 150000:
        raise SessionLimitReachedException(token_count)
    
    # Create the message with streaming enabled
    response = client.messages.create(
        max_tokens=max_tokens,
        system = system,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        model=model,
        stream=stream,
    )

    final_response = ""
    # Print the streamed response incrementally
    for event in response:
        # Check if the event is a content block delta
        if hasattr(event, 'delta') and hasattr(event.delta, 'text'):
            # Print the text incrementally, without adding a new line
            print(event.delta.text, end="")
            final_response += event.delta.text

    print()  # Add a final newline for clean output after the loop
    return final_response.strip()
