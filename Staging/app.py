import flask
import redis
import uuid
import os
import json
from dotenv import load_dotenv
from main import initialize_models, generate_response
from flask import Response, request, jsonify
from functools import wraps
from main import generate_response
import time
from functools import wraps
from redis.exceptions import ConnectionError, TimeoutError
import logging
from logging.handlers import RotatingFileHandler
from google.api_core.exceptions import ServiceUnavailable
from claude_sonnet import SessionLimitReachedException

# Setup basic configuration - This is placed at the beginning to configure the root logger.
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Configure a specific logger for your application
logger = logging.getLogger(__name__)
log_file_path = '/tmp/chatbot-staging.log'
log_file = log_file_path
file_handler = RotatingFileHandler(log_file, maxBytes=10240, backupCount=5)  # 10 KB per file, 5 files backup
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)
logger.setLevel(logging.DEBUG) 

# Load environment variables from the .env file
load_dotenv()

app = flask.Flask(__name__)

redis_host = os.getenv('STAGING_REDIS_HOST', '10.125.74.235')
redis_port = int(os.getenv('STAGING_REDIS_PORT', 6379))

r = redis.Redis(host=redis_host, port=redis_port, db=0)


# Initialize models only once when the application starts
#models = initialize_models(system_instruction)

# Get the API key from the environment variables
STAGING_API_KEY = os.getenv('STAGING_API_KEY')

def get_or_create_session(user_id, user_name):
    # Check if a session key for this user already exists
    session_key_pattern = f"user:{user_id}:*"
    existing_keys = r.keys(session_key_pattern)
    
    if existing_keys:
        # If a session already exists, use that
        session_key = existing_keys[0].decode('utf-8')

        # Check if the key is a hash, if not delete and recreate it
        if r.type(session_key) != b'hash':
            print(f"Key {session_key} exists but is not a hash. Deleting and recreating.")
            r.delete(session_key)
            session_key = None
    if not existing_keys or session_key is None:
        # Otherwise, create a new session
        session_id = str(uuid.uuid4())
        session_key = f"user:{user_id}:{session_id}"
        
        # Ensure that the key does not exist or is a hash
        if r.exists(session_key):
            r.delete(session_key)
        
        # Initialize the session key as a hash
        r.hset(session_key, "user_id", user_id)
        r.hset(session_key, "user_name", user_name)
        r.hset(session_key, "conversation_history", "")
    
    return session_key

def update_session(session_key, user_input, model_response):
    # Ensure the key is a hash before updating
    if r.type(session_key) != b'hash':
        print(f"Key {session_key} is not a hash. Deleting and recreating the session key.")
        r.delete(session_key)  # Delete the incorrect key
        raise ValueError(f"Key {session_key} is not a hash and was deleted.")
    
    # Get the current conversation history (if any) as a list
    conversation_history = r.hget(session_key, "conversation_history")
    
    if conversation_history:
        try:
            conversation_history = json.loads(conversation_history.decode('utf-8'))  # Convert JSON string to Python list
        except json.JSONDecodeError:
            # Handle the case where the JSON is invalid
            conversation_history = []
            print(f"Warning: Corrupted JSON in {session_key}. Resetting conversation history.")
    else:
        conversation_history = []  # Initialize as an empty list if no history exists

    # Append new conversation data as dictionaries to the list
    conversation_history.append({"role": "user", "content": user_input})
    conversation_history.append({"role": "assistant", "content": model_response})

    # Save the updated list back to Redis as a JSON string
    r.hset(session_key, "conversation_history", json.dumps(conversation_history))

# Replace print in require_api_key and exception handling in routes
def require_api_key(view_function):
    @wraps(view_function)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        logger.debug("Authorization Header: %s", auth_header)
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            logger.debug("Token extracted: %s", token)
            if token == STAGING_API_KEY:
                return view_function(*args, **kwargs)
        logger.info("Unauthorized API Key attempted to access.")
        return jsonify({"error": "Unauthorized API Key"}), 401
    return decorated_function

@app.route('/chat2/start_session', methods=['POST'])
@require_api_key
def start_session():
    try:
        # Parse JSON data from the request
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data received"}), 400

        # Extract user data from the request
        user_id = data.get('user_id')
        user_name = data.get('user_name')
        user_input = data.get('message')

        # Ensure all required fields are present
        if not user_id:
            return jsonify({"error": "Missing user_id"}), 400
        if not user_name:
            return jsonify({"error": "Missing user_name"}), 400
        if not user_input:
            return jsonify({"error": "Missing message"}), 400
        # Ensure all required fields are present
        if not user_id or not user_name or not user_input:
            return jsonify({"error": "Missing required fields"}), 400

        # Get or create a session for the user
        session_key = get_or_create_session(user_id, user_name)
        
        model_choice = "claude"  # Adjust as needed

        # Generate a response from the model
        response_generator = generate_response(user_input, model_choice, session_key, r, user_id)
        #response_chunks = []
        #def generate():
        #    for chunk in response_generator:
        #        response_chunks.append(chunk)
        #        yield chunk
         #   # Once all chunks are generated, concatenate them and update the session
        #    full_response = ''.join(response_chunks)
        #    update_session(session_key, user_input, full_response)

        #return Response(generate(), content_type='text/plain')
        # Prepare and send the streaming JSON response
        response_chunks = []
        def generate():
            yield '{"response": "'
            for chunk in response_generator:
                chunk = chunk.replace('\n', '\\n').replace('"', '\\"').replace('*','')
                response_chunks.append(chunk)
                yield chunk
            yield '"}'
            full_response = ''.join(response_chunks)
            update_session(session_key, user_input, full_response)

        return Response(generate(), content_type='application/json')

     # Catch token limit exception (HTTP 413)
    except SessionLimitReachedException as e:
        logger.exception("Token limit exceeded: %s", str(e))
        return jsonify({"error": e.message}), 413

    # Catch gRPC's ServiceUnavailable exception
    except ServiceUnavailable as e:
        logger.exception("Service unavailable, error: %s", str(e))
        return jsonify({"error": "Service Unavailable"}), 503

    # Catch any other unexpected exceptions
    except Exception as e:
        logger.exception("Unexpected error: %s", str(e))
        return jsonify({"error": "Service Unavailable"}), 503 


@app.route('/chat2/end_session', methods=['POST'])
@require_api_key
def end_session():
    try:
        # Use request.get_json() to parse JSON data from the request
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data received"}), 400
        
        user_id = data.get('user_id')

        # Ensure the user_id is provided
        if not user_id:
            return jsonify({"error": "Missing required fields"}), 400

        session_key_pattern = f"user:{user_id}:*"
        existing_keys = r.keys(session_key_pattern)
        
        if existing_keys:
            session_key = existing_keys[0].decode('utf-8')
            r.delete(session_key)
            return jsonify({"message": "Session ended successfully"}), 200
        else:
            return jsonify({"error": "No active session found"}), 404

    except Exception as e:
        print(f"An error occurred: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@app.route('/')
def home():
    return "Flask server is running!"

if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=6000)