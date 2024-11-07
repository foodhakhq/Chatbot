# mistral_model.py

import json
import subprocess
import requests

MODEL = "mistral-large"
LOCATION = "us-central1"
PROJECT_ID = "central-muse-388319"
ENDPOINT = f"https://{LOCATION}-aiplatform.googleapis.com"

def get_access_token():
    process = subprocess.Popen(
        "gcloud auth print-access-token", stdout=subprocess.PIPE, shell=True
    )
    (access_token_bytes, err) = process.communicate()
    return access_token_bytes.decode("utf-8").strip()

def generate_response_with_mistral(prompt, max_tokens=1024):
    access_token = get_access_token()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": True,
    }

    request_data = json.dumps(payload)
    url = f"{ENDPOINT}/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/mistralai/models/{MODEL}:streamRawPredict"

    response = requests.post(url, headers=headers, data=request_data, stream=True)

    if response.status_code == 200:
        final_response = ""
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8').strip()

                if decoded_line.startswith("data: "):
                    try:
                        data_json = json.loads(decoded_line[len("data: "):])

                        if 'choices' in data_json:
                            for choice in data_json['choices']:
                                if 'delta' in choice and 'content' in choice['delta']:
                                    content_part = choice['delta']['content']
                                    print(content_part, end="", flush=True)  # Stream content
                                    final_response += content_part

                    except json.JSONDecodeError:
                        continue
        return final_response.strip()
    else:
        print(f"Request failed with status code: {response.status_code}")
        return "N/A"
