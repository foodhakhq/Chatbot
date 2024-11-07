# gemini_model.py

import time
from google.api_core.exceptions import ServiceUnavailable, BadGateway
import vertexai
from vertexai.preview.generative_models import GenerativeModel
import vertexai.preview.generative_models as generative_models

def initialize_gemini_model(project_id, location, system_instruction):
    vertexai.init(project=project_id, location=location)
    # Pass system_instruction to the GenerativeModel
    return GenerativeModel(
        "gemini-1.5-pro-001",
        system_instruction=[system_instruction]  # Pass the system instruction here
    )


def generate_response_with_gemini(model, prompt):
    try:
        response_generator = model.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": 1024,
                "temperature": 0,
                "top_p": 1,
            },
            safety_settings={
                generative_models.HarmCategory.HARM_CATEGORY_HATE_SPEECH: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                generative_models.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                generative_models.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                generative_models.HarmCategory.HARM_CATEGORY_HARASSMENT: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            },
            stream=True  # Enable streaming for real-time responses
        )

        final_response = ""
        for part in response_generator:
            print(part.text, end="", flush=True)
            final_response += part.text

        return final_response.strip()

    except (ServiceUnavailable, BadGateway) as e:
        print(f"Caught error: {e}, retrying after a delay...")
        time.sleep(10)
        return generate_response_with_gemini(model, prompt)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return "N/A"
