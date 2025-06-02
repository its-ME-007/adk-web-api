# --- Import necessary libraries ---
from google.adk.agents import LlmAgent, Agent, ParallelAgent
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
import json # Import json to parse the secret content
from google.cloud import secretmanager # Import Secret Manager client

# Load environment variables from .env file (useful for local testing)
load_dotenv()

PROJECT_ID = "image-gen-34b6b" # Get project ID from env var, fallback to hardcoded
SECRET_ID = "firebase-agents-creds" # Get secret ID from env var, fallback
SECRET_VERSION_ID =  "latest" # Get secret version from env var, fallback

# --- Function to Access Secret Manager ---
def access_secret_version(project_id, secret_id, version_id):
    """Access the secret version and return its payload."""
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode('UTF-8')
    except Exception as e:
        print(f"Error accessing Secret Manager secret '{secret_id}': {e}")
        return None

# --- Firebase Initialization ---
if not firebase_admin._apps:
    print("Attempting to initialize Firebase Admin SDK...")
    credentials_json_string = None
    cred = None

    if PROJECT_ID and SECRET_ID and SECRET_VERSION_ID:
        credentials_json_string = access_secret_version(PROJECT_ID, SECRET_ID, SECRET_VERSION_ID)

    if credentials_json_string:
        try:
            cred = credentials.Certificate(json.loads(credentials_json_string))
            firebase_admin.initialize_app(cred)
            print("Successfully initialized Firebase with Secret Manager credentials.")
        except Exception as e:
            print(f"ERROR initializing Firebase with Secret Manager credentials: {str(e)}")
            print("Attempting to initialize Firebase with application default credentials.")
            try:
                 firebase_admin.initialize_app()
                 print("Successfully initialized Firebase with application default credentials.")
            except Exception as e_default:
                 print(f"ERROR initializing Firebase with application default credentials: {str(e_default)}")
                 print("Firebase initialization failed entirely.")

    else:
        print("Secret Manager credentials not available or fetching failed. Attempting application default credentials.")
        try:
            firebase_admin.initialize_app()
            print("Successfully initialized Firebase with application default credentials.")
        except Exception as e_default:
            print(f"ERROR initializing Firebase with application default credentials: {str(e_default)}")
            print("Firebase initialization failed entirely.")

db = None 
if firebase_admin._apps: 
    try:
        db = firestore.client(database_id="prompts-saved") # Use the database ID as needed
        print("Successfully connected to Firestore")
    except Exception as e:
        print(f"ERROR connecting to Firestore: {str(e)}")
        print("Firestore client could not be created.")

def save_response_to_file_and_db(response_content: str, agent_name: str) -> str:
    """
    Writes the provided response content from a specific agent to a dedicated file and saves it to Firebase.

    Args:
        response_content (str): The actual text content of the response to be saved.
        agent_name (str): The name of the agent (e.g., 'Information_Designer', 'Safety_Officer', 'Coordination_Planner')
                          whose response is being saved. This determines the filename and the database record.

    Returns:
        str: A confirmation message indicating the file path where the response was saved or an error message.
    """

    try:
        if isinstance(db, firestore.Client):
             agent_responses_ref = db.collection('agent_responses')
             add_result = agent_responses_ref.add({ 
                 'agent_name': agent_name,
                 'response_content': response_content,
                 'created_at': firestore.SERVER_TIMESTAMP
             })
             print(f"Saved to Firestore with ID: {add_result[1].id}") 

        return f"Successfully saved response from {agent_name} to Firebase database."

    except Exception as e:
        return f"Error saving response from {agent_name} to Firebase database: {str(e)}"
    
agent_information_designer_parallel = LlmAgent(
    name="Information_Designer",
    model="gemini-2.0-flash-exp",
    description="An AI agent that ensures interface clarity by prioritizing essential information, reducing cognitive load, and organizing content for effective decision-making.",
    instruction="Focus on helping the user design a clean, readable interface. Suggest ways to highlight critical data, reduce screen clutter, and enhance usability under high-pressure conditions.",
    output_key="info_response",
)

agent_safety_officer_parallel = LlmAgent(
    name="Safety_Officer",
    model="gemini-2.0-flash-exp",
    description="An AI agent responsible for identifying potential safety risks and ensuring the interface supports real-time safety monitoring and emergency responses.",
    instruction="Prompt the user to consider real-world safety hazards. Suggest necessary alerts, overrides, and interlocks that should be visible on the HMI to support operator safety.",
    output_key="safety_response",
)

agent_coordination_planner_parallel = LlmAgent(
    name="Coordination_Planner",
    model="gemini-2.0-flash-exp",
    description="An AI agent focused on timing, sequencing, and dependencies between robots and production stages to ensure smooth task coordination.",
    instruction="Guide the user in thinking through how the HMI can help manage inter-robot timing, production delays, or task handoffs. Suggest synchronization features or warnings for disrupted flows.",
    output_key="coordination_response",
)

gather_concurrently = ParallelAgent(
    name="ConcurrentFetch",
    sub_agents=[agent_information_designer_parallel, agent_safety_officer_parallel,agent_coordination_planner_parallel ],
)

root_agent = Agent(
    name="DisplayAndSaveAgent",
    model="gemini-2.0-flash-exp",
    sub_agents=[gather_concurrently],
    description="This agent gathers information from Information Designer, Safety Officer, and Coordination Planner sub-agents, displays it, and saves specific responses to files and the database upon user request.",
    instruction=(
        "Your primary role is to orchestrate the information flow and interact with the user.\n"
        "Greet the user and explain that you will gather insights from three agents: Information Designer, Safety Officer, and Coordination Planner. Then follow the steps given post this.\n"
        "1. First, execute the 'ConcurrentFetch' parallel agent. This will run the Information_Designer, Safety_Officer, and Coordination_Planner agents. Their responses will be available in your context under the keys 'info_response', 'safety_response', and 'coordination_response'.\n"
        "2. Once you have the responses, don't synthesize any answers. You are to present them clearly to the user. Use bullet points or distinct sections, clearly indicating which response came from which agent (e.g., 'Information Designer Perspective:', 'Safety Officer Insights:', 'Coordination Planner Details:').\n"
        "3. After presenting the information, explicitly ask the user if they would like to save the response from any specific agent (e.g., 'Would you like me to save the response from the Information Designer, Safety Officer, or Coordination Planner?').\n"
        "4. *If and only if* the user confirms they want to save a response and specifies which one (e.g., 'Yes, save the Information Designer response', 'Save the Safety Officer's part'):\n"
        "   a. Identify the target agent name ('Information_Designer', 'Safety_Officer', or 'Coordination_Planner').\n"
        "   b. Retrieve the complete text of that agent's response from your context using the corresponding key ('info_response', 'safety_response', or 'coordination_response').\n"
        "   c. Call the save_response_to_file_and_db tool. \n"
        "   d. Pass the retrieved text as the response_content argument.\n"
        "   e. Pass the identified agent name (e.g., 'Information_Designer') as the agent_name argument.\n"
        "   f. Report the outcome (success or error message returned by the tool) back to the user.\n"
        "5. *Crucially: Do NOT run the 'ConcurrentFetch' agent again just to save a file.* Use the responses you already obtained in step 1.\n"
        "6. If the user asks a follow-up question or provides a new query not related to saving, handle it appropriately, potentially by re-running 'ConcurrentFetch' if new perspectives are needed for a new topic. Be aware that the Information Designer agent has access to interface design tools if the user asks for specific design insights."
    ),
    tools=[save_response_to_file_and_db], 
)