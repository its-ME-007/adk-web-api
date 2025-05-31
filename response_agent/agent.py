# --- Import necessary libraries ---
from google.adk.agents import LlmAgent, Agent, ParallelAgent
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
import json
from google.cloud import secretmanager

load_dotenv()

PROJECT_ID = "image-gen-34b6b"
SECRET_ID = "firebase-agents-creds"
SECRET_VERSION_ID = "latest"

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
        db = firestore.client(database_id="prompts-saved")
        print("Successfully connected to Firestore")
    except Exception as e:
        print(f"ERROR connecting to Firestore: {str(e)}")
        print("Firestore client could not be created.")

# --- Tool Functions ---
def display_saved_prompts() -> str:
    """
    Retrieves and displays all saved agent responses from the Firebase 'agent_responses' collection.
    
    Returns:
        str: A formatted string containing all saved prompts with agent names, timestamps, 
             and response content, or an error message if retrieval fails.
    """
    try:
        if not isinstance(db, firestore.Client):
            return "Error: Firebase database connection not available."
        
        agent_responses_ref = db.collection('agent_responses')
        docs = agent_responses_ref.order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        docs_list = list(docs)
        
        if not docs_list:
            return "No saved prompts found in the database."
        
        formatted_output = "=== AVAILABLE PROMPTS FOR GRADING ===\n\n"
        
        for i, doc in enumerate(docs_list, 1):
            doc_data = doc.to_dict()
            agent_name = doc_data.get('agent_name', 'Unknown Agent')
            response_content = doc_data.get('response_content', 'No content available')
            created_at = doc_data.get('created_at')
            
            if created_at:
                try:
                    timestamp_str = created_at.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    timestamp_str = "Unknown time"
            else:
                timestamp_str = "Unknown time"
            
            # Show first 100 characters of content as preview
            content_preview = response_content[:100] + "..." if len(response_content) > 100 else response_content
            
            formatted_output += f"{i}. Agent: {agent_name} | Saved: {timestamp_str}\n"
            formatted_output += f"   Preview: {content_preview}\n"
            formatted_output += f"   Document ID: {doc.id}\n\n"
        
        return formatted_output
        
    except Exception as e:
        return f"Error retrieving saved prompts from Firebase database: {str(e)}"

def get_prompt_by_number(prompt_number: int) -> str:
    """
    Retrieves a specific prompt by its display number.
    
    Args:
        prompt_number (int): The number of the prompt as shown in display_saved_prompts()
        
    Returns:
        str: The full content of the selected prompt or an error message.
    """
    try:
        if not isinstance(db, firestore.Client):
            return "Error: Firebase database connection not available."
        
        agent_responses_ref = db.collection('agent_responses')
        docs = agent_responses_ref.order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        docs_list = list(docs)
        
        if not docs_list:
            return "No saved prompts found in the database."
        
        if prompt_number < 1 or prompt_number > len(docs_list):
            return f"Invalid prompt number. Please select a number between 1 and {len(docs_list)}."
        
        selected_doc = docs_list[prompt_number - 1]
        doc_data = selected_doc.to_dict()
        
        agent_name = doc_data.get('agent_name', 'Unknown Agent')
        response_content = doc_data.get('response_content', 'No content available')
        
        return f"Selected Prompt from {agent_name}:\n\n{response_content}"
        
    except Exception as e:
        return f"Error retrieving prompt: {str(e)}"

# --- DISPLAY AGENT ---
agent_display = LlmAgent(
    name="Display_Agent",
    model="gemini-2.0-flash-exp",
    description="Presents prompts to users in a numbered list and supports selection by number or description.",
    instruction=(
        "Your role is to display prompts from the database in a user-friendly numbered format. "
        "When asked to show prompts, use the display_saved_prompts tool to get all prompts. "
        "Present them clearly with numbers for easy selection. "
        "do not present the document ID in the display, only the agent name, timestamp, and content preview. "
        "When a user selects a prompt by number, use the get_prompt_by_number tool to retrieve the full content. "
        "Always format your responses clearly with proper numbering and ask users to pick by number."
    ),
    output_key="display_response",
    tools=[display_saved_prompts, get_prompt_by_number],
)

agent_safety_officer = LlmAgent(
    name="Safety_Officer_Agent",
    model="gemini-2.0-flash-exp",
    description="Evaluates the safety implications and risk awareness of prompts.",
    instruction=(
        "You are a safety expert analyzing prompts for safety considerations. "
        "Rate each prompt on a scale of 1-10 based on: "
        "• Safety awareness and risk assessment "
        "• Harm prevention measures "
        "• Emergency response considerations "
        "• Risk mitigation strategies "
        "Always provide your rating in this format: "
        "'SAFETY SCORE: X/10 - [brief safety feedback and reasoning]' "
        "Focus on identifying potential hazards and safety improvements."
    ),
    output_key="safety_response",
)

agent_information_designer = LlmAgent(
    name="Information_Designer_Agent",
    model="gemini-2.0-flash-exp",
    description="Evaluates information clarity and communication quality of prompts.",
    instruction=(
        "You are an information design expert evaluating prompts for communication effectiveness. "
        "Rate each prompt on a scale of 1-10 based on: "
        "• Clarity of language and instructions "
        "• Information structure and organization "
        "• Readability and appropriate tone "
        "• Logical flow of information "
        "Always provide your rating in this format: "
        "'INFO DESIGN SCORE: X/10 - [rationale for clarity and communication quality]' "
        "Focus on how well the information is presented and understood."
    ),
    output_key="info_response",
)

agent_coordination_planner = LlmAgent(
    name="Coordination_Planner_Agent",
    model="gemini-2.0-flash-exp",
    description="Evaluates coordination logic, role clarity, and task planning in prompts.",
    instruction=(
        "You are a coordination expert analyzing prompts for task management effectiveness. "
        "Rate each prompt on a scale of 1-10 based on: "
        "• Clarity in task delegation and role definition "
        "• Time and resource management considerations "
        "• Workflow coordination and dependencies "
        "• Team collaboration aspects "
        "Always provide your rating in this format: "
        "'COORDINATION SCORE: X/10 - [justification for coordination effectiveness]' "
        "Focus on how well the prompt facilitates teamwork and task management."
    ),
    output_key="coordination_response",
)

# --- PARALLEL GRADING AGENT ---
grading_parallel_agent = ParallelAgent(
    name="ConcurrentGrading",
    sub_agents=[ agent_safety_officer, agent_information_designer, agent_coordination_planner],
    description="Runs all grading agents in parallel to evaluate a selected prompt.",
)

# --- COMPOSITE SCORING AGENT ---
agent_composite_scorer = LlmAgent(
    name="Composite_Scorer_Agent",
    model="gemini-2.0-flash-exp",
    description="Combines feedback from all grading agents and creates a comprehensive summary.",
    instruction=(
        "You are responsible for creating a final comprehensive grading report. "
        "You will receive responses from Designer, Safety Officer, Information Designer, and Coordination Planner agents. "
        "Your task is to: "
        "1. Extract the numeric scores from each agent's response "
        "2. Calculate the average score "
        "3. Identify the strongest and weakest aspects "
        "4. Create a final summary report in this format: "
        "```"
        "=== COMPREHENSIVE GRADING REPORT ==="
        "Final Average Rating: X.X/10"
        ""
        "Individual Scores:"
        "• Design Quality: X/10"
        "• Safety Considerations: X/10"
        "• Information Clarity: X/10"
        "• Coordination Planning: X/10"
        ""
        "Strengths: [highlight best aspects]"
        "Areas for Improvement: [identify weaknesses]"
        ""
        "Overall Assessment: [brief overall evaluation]"
        "```"
        "Be objective and provide actionable insights."
    ),
    output_key="composite_response",
)

# --- ROOT AGENT - DISPLAY GRADING AGENT ---
root_agent = Agent(
    name="Display_Grading_Agent",
    model="gemini-2.0-flash-exp", 
    sub_agents=[agent_display, grading_parallel_agent, agent_composite_scorer],
    description="Main orchestrator that greets users, manages prompt display, coordinates grading, and provides final reports.",
    instruction=(
        "You are the main Display Grading Agent - a friendly orchestrator for the prompt grading system. "
        ""
        "GREETING PHASE:"
        "1. Start with a warm, varied greeting like:"
        "   • 'Hello! 👋 How are you today?'"
        "   • 'Hey there! What would you like to do?'"
        "   • 'Welcome to the Prompt Grading System!'"
        ""
        "2. Ask the user what they'd like to do:"
        "   • 'Would you like to grade all prompts or select specific ones?'"
        "   • 'How can I help you with prompt grading today?'"
        ""
        "WORKFLOW MANAGEMENT:"
        "3. Based on user response:"
        "   • If 'grade all' or 'show all': Use Display Agent to show all prompts"
        "   • If 'grade specific' or 'select few': Use Display Agent for selection"
        ""
        "4. When user selects a prompt (e.g., 'Prompt 2', 'number 3'):"
        "   • Use Display Agent to get the full prompt content"
        "   • Pass the selected prompt to the 'ConcurrentGrading' parallel agent"
        "   • Wait for all grading responses (designer_response, safety_response, info_response, coordination_response)"
        ""
        "5. After receiving grading responses:"
        "   • Pass all responses to the Composite Scorer Agent for final analysis"
        "   • Present the comprehensive report to the user"
        ""
        "6. Ask if they want to:"
        "   • Grade another prompt"
        "   • See the detailed individual agent feedback"
        "   • Get recommendations for improvement"
        ""
        "IMPORTANT RULES:"
        "• Always be friendly and helpful"
        "• Don't run grading until a specific prompt is selected"
        "• Present information clearly with proper formatting"
        "• Handle errors gracefully and offer alternatives"
        "• Keep the user engaged throughout the process"
    ),
    tools=[],
)