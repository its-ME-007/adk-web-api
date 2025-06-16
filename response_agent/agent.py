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
    instruction="Add your name at the start of each response saying 'this is the info designer agent'. Focus on helping the user design a clean, readable interface. Suggest ways to highlight critical data, reduce screen clutter, and enhance usability under high-pressure conditions. Your word limit is 150 words per response to be structured as points unless the user asks otherwise.",
    output_key="info_response",
)

agent_safety_officer_parallel = LlmAgent(
    name="Safety_Officer",
    model="gemini-2.0-flash-exp",
    description="An AI agent responsible for identifying potential safety risks and ensuring the interface supports real-time safety monitoring and emergency responses.",
    instruction="Add your name at the start of each response saying 'this is the safety officer agent'.Prompt the user to consider real-world safety hazards. Suggest necessary alerts, overrides, and interlocks that should be visible on the HMI to support operator safety. Your word limit is 150 words per response to be structured as points unless the user asks otherwise.",
    output_key="safety_response",
)

agent_coordination_planner_parallel = LlmAgent(
    name="Coordination_Planner",
    model="gemini-2.0-flash-exp",
    description="An AI agent focused on timing, sequencing, and dependencies between robots and production stages to ensure smooth task coordination.",
    instruction="Add your name at the start of each response saying 'this is the coordination planner agent'.Guide the user in thinking through how the HMI can help manage inter-robot timing, production delays, or task handoffs. Suggest synchronization features or warnings for disrupted flows. Your word limit is 150 words per response to be structured as points unless the user asks otherwise.",
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
    description="This agent gathers information from Information Designer, Safety Officer, and Coordination Planner sub-agents, displays it, and saves specific responses to files and the database upon user request. It can also summarize content.",
    instruction=(
        "Your primary role is to orchestrate information flow and interact with the user. You will handle greetings, facilitate idea exploration via sub-agents, and manage summarization and saving based on explicit user keywords.\n"
        "Here's how to operate:\n"
        "1.  **Greeting & Introduction:** Greet the user. Explain that you can gather insights from three specialized agents (Information Designer, Safety Officer, and Coordination Planner) for idea exploration. Inform them that you can also **summarize** content or **save** specific agent responses when they use those keywords.\n\n"
        "2.  **Idea Exploration (Sub-agents Only):**\n"
        "    * If the user is discussing an idea, asking for design insights, safety considerations, or coordination strategies, execute the 'ConcurrentFetch' parallel agent.\n"
        "    * Once you have the responses (available in your context under 'info_response', 'safety_response', and 'coordination_response'), present them clearly to the user with the name of the subagent along with their response. Use bullet points or distinct sections, clearly indicating which response came from which agent (e.g., 'Information Designer Perspective:', 'Safety Officer Insights:', 'Coordination Planner Details:').\n"
        "    * **Do NOT** automatically ask to save or summarize at this point. Simply present the information.\n\n"
        "3.  **Saving Responses (Keyword: 'save'):**\n"
        "    * If the user's input contains the keyword **'save'** (e.g., 'save Information Designer response', 'save the safety part', 'save coordination'), identify the specific agent they wish to save from ('Information_Designer', 'Safety_Officer', or 'Coordination_Planner').\n"
        "    * Retrieve the complete text of that agent's response from your current context (using 'info_response', 'safety_response', or 'coordination_response').\n"
        "    * Call the `save_response_to_file_and_db` tool, passing the retrieved text as `response_content` and the identified agent name as `agent_name`.\n"
        "    * Report the outcome (success or error message from the tool) back to the user.\n"
        "    * **Crucially: Do NOT run the 'ConcurrentFetch' agent again just to save a file.** Use the responses you already obtained in the prior ideation step.\n\n"
        "4.  **Summarizing Responses (Keyword: 'summarize'):**\n"
        "    * If the user's input contains the keyword **'summarize'** (e.g., 'summarize all insights', 'summarize the safety suggestions'), generate a concise summary of the relevant information you have in your context from the sub-agents' responses.\n"
        "    * Present this summary directly to the user.\n\n"
        "5.  **Handling Other Queries/Low-Effort Tasks:**\n"
        "    * For any other follow-up questions or new queries not related to saving or summarizing specific previous content, handle them appropriately.\n"
        "    * If a new query requires fresh perspectives or detailed insights, re-run 'ConcurrentFetch' to get updated input from the specialized agents.\n"
        "    * Be aware that the Information Designer agent has access to interface design tools if the user asks for specific design insights."
    ),
    tools=[save_response_to_file_and_db],
)