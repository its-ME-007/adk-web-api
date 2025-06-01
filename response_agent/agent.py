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
from typing import List, Dict, Any

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
             and response content previews.
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

            timestamp_str = created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else "Unknown time"
            content_preview = response_content[:100] + "..." if len(response_content) > 100 else response_content

            formatted_output += f"{i}. Agent: {agent_name} | Saved: {timestamp_str}\n"
            formatted_output += f"   Preview: {content_preview}\n\n"

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

def create_score_table(safety_score: str, info_score: str, coordination_score: str) -> str:
    """
    Creates a markdown table with agent scores.
    
    Args:
        safety_score (str): Safety officer score (e.g., "8/10")
        info_score (str): Information designer score (e.g., "7/10")
        coordination_score (str): Coordination planner score (e.g., "9/10")
    
    Returns:
        str: Formatted markdown table with scores
    """
    try:
        table = f"""
| Agent | Score |
|-------|-------|
| Safety Officer | {safety_score} |
| Information Designer | {info_score} |
| Coordination Planner | {coordination_score} |
"""
        return table.strip()
    except Exception as e:
        return f"Error creating score table: {str(e)}"

# --- DISPLAY AGENT ---
agent_display = LlmAgent(
    name="Display_Agent",
    model="gemini-2.0-flash-exp",
    description="Presents prompts to users in a numbered list and supports selection by number.",
    instruction=(
        "Your role is to display prompts from the database in a user-friendly numbered format. "
        "When asked to show prompts, use the display_saved_prompts tool to get all prompts. "
        "Present them clearly with numbers for easy selection. "
        "Do not present the document ID in the display, only the agent name, timestamp, and content preview. "
        "When a user selects a prompt by number, use the get_prompt_by_number tool to retrieve the full content. "
        "Always format your responses clearly with proper numbering and ask users to pick by number."
    ),
    output_key="display_response",
    tools=[display_saved_prompts, get_prompt_by_number],
)

agent_technical_feasibility = Agent(
    name="Technical_Feasibility_Agent",
    model="gemini-2.0-flash-exp",
    description="Evaluates the technical viability and implementation aspects of prompts.",
    instruction=(
        "You are a Technical Feasibility Grading Agent. "
        "Evaluate prompts based on technical implementation feasibility. "
        ""
        "GRADING CRITERIA (Score 1-10):"
        "• Technical Complexity: Is the request technically achievable with current technology?"
        "• Resource Requirements: Are the computational/technical resources reasonable?"
        "• Implementation Clarity: Is the technical approach clear and well-defined?"
        "• Scalability: Can the solution scale effectively?"
        "• Technical Risk Assessment: What are the potential technical challenges?"
        ""
        "RESPONSE FORMAT:"
        "TECHNICAL FEASIBILITY SCORE: X/10"
        "TECHNICAL FEASIBILITY FEEDBACK: [Provide specific technical insights, "
        "implementation considerations, potential challenges, and recommendations "
        "for technical improvement. Be concise but thorough.]"
        ""
        "Focus on practical technical aspects and real-world implementation viability."
    ),
    tools=[],
)

agent_industry_relevance = Agent(
    name="Industry_Relevance_Agent", 
    model="gemini-2.0-flash-exp",
    description="Assesses market relevance and industry application potential of prompts.",
    instruction=(
        "You are an Industry Relevance Grading Agent. "
        "Evaluate prompts based on their relevance to current industry needs and market demands. "
        ""
        "GRADING CRITERIA (Score 1-10):"
        "• Market Demand: Does this address a real industry need or pain point?"
        "• Business Value: What's the potential ROI and business impact?"
        "• Industry Trends: How well does this align with current industry trends?"
        "• Competitive Advantage: Does this provide meaningful differentiation?"
        "• Adoption Potential: How likely are businesses to adopt this solution?"
        ""
        "RESPONSE FORMAT:"
        "INDUSTRY RELEVANCE SCORE: X/10"
        "INDUSTRY RELEVANCE FEEDBACK: [Provide specific market insights, "
        "industry applications, competitive landscape analysis, and business "
        "value assessment. Include relevant industry examples where applicable.]"
        ""
        "Focus on commercial viability and real-world business applications."
    ),
    tools=[],
)

agent_innovation = Agent(
    name="Innovation_Agent",
    model="gemini-2.0-flash-exp", 
    description="Evaluates creativity, novelty, and innovative aspects of prompts.",
    instruction=(
        "You are an Innovation Grading Agent. "
        "Evaluate prompts based on their innovative potential and creative approach. "
        ""
        "GRADING CRITERIA (Score 1-10):"
        "• Novelty: How original and unique is this approach?"
        "• Creative Problem-Solving: Does it show innovative thinking?"
        "• Disruptive Potential: Could this change existing paradigms?"
        "• Cross-Domain Innovation: Does it combine ideas from different fields?"
        "• Future Impact: What's the potential for long-term innovation?"
        ""
        "RESPONSE FORMAT:"
        "INNOVATION SCORE: X/10"
        "INNOVATION FEEDBACK: [Provide specific innovation insights, "
        "creative aspects, potential for disruption, and suggestions for "
        "enhancing innovative elements. Highlight unique approaches.]"
        ""
        "Focus on creative thinking, originality, and transformative potential."
    ),
    tools=[],
)

# --- PARALLEL GRADING AGENT ---
grading_parallel_agent = ParallelAgent(
    name="ConcurrentGrading",
    sub_agents=[agent_technical_feasibility,agent_industry_relevance ,agent_innovation ],
    description="Runs all grading agents in parallel to evaluate a selected prompt.",
)

# --- COMPOSITE SCORING AGENT ---
agent_composite_scorer = LlmAgent(
    name="Composite_Scorer_Agent",
    model="gemini-2.0-flash-exp",
    description="Combines feedback from all grading agents and creates comprehensive summaries or tabular rankings.",
    instruction=(
        "You are responsible for creating grading reports in two formats: "
        ""
        "FORMAT 1 - COMPREHENSIVE REPORT (when detailed analysis is requested):"
        "1. Extract the numeric scores from each agent's response. "
        "2. Calculate the average score. "
        "3. Identify the strongest and weakest aspects based on the feedback. "
        "4. Create a final summary report in this format: "
        "```"
        "=== COMPREHENSIVE GRADING REPORT ==="
        "Final Average Rating: X.X/10"
        ""
        "Individual Scores:"
        "• Safety Considerations: X/10"
        "• Information Clarity: X/10"
        "• Coordination Planning: X/10"
        ""
        "Strengths: [highlight best aspects]"
        "Areas for Improvement: [identify weaknesses]"
        ""
        "Overall Assessment: [brief overall evaluation]"
        "```"
        ""
        "FORMAT 2 - TABULAR RANKING (when table format is requested):"
        "Use the create_score_table tool by passing the individual scores as parameters. "
        "Extract just the score portion (e.g., '8/10') from each agent's response and pass them to the tool."
        ""
        "Be objective and provide actionable insights."
    ),
    output_key="composite_response",
    tools=[create_score_table],
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
        "1. Start with a warm, varied greeting."
        "2. Ask the user what they'd like to do (e.g., 'grade all', 'select specific')."
        ""
        "WORKFLOW MANAGEMENT:"
        "3. Based on user response, use Display Agent to show or select prompts."
        "4. When a user selects a prompt by number:"
        "   a. Use Display Agent to get the full prompt content."
        "   b. Pass the selected prompt to 'ConcurrentGrading'."
        "   c. Wait for all grading responses (safety_response, info_response, coordination_response)."
        ""
        "5. Present the initial grading results with scores on one line and brief feedback on the next line for each agent."
        "   Format as: '[AGENT NAME] SCORE: X/10\n[AGENT NAME] FEEDBACK: [brief feedback]'"
        ""
        "6. Ask the user: 'Would you like to see the grading results in a table or a detailed composite report?'"
        ""
        "7. If the user asks for 'table':"
        "   a. Extract the individual scores (just the 'X/10' portion) from safety_response, info_response, and coordination_response."
        "   b. Pass these scores as parameters to the Composite Scorer Agent, which will use its create_score_table tool."
        "   c. Present the tabular output to the user."
        ""
        "8. If the user asks for 'detailed report':"
        "   a. Pass all grading responses to the Composite Scorer Agent for comprehensive analysis."
        "   b. Present the comprehensive report to the user."
        ""
        "9. Ask if they want to grade another prompt or have further questions."
        ""
        "IMPORTANT RULES:"
        "• Always be friendly and helpful."
        "• Don't run grading until a specific prompt is selected."
        "• Present information clearly with proper formatting."
        "• Handle errors gracefully and offer alternatives."
        "• Keep the user engaged."
        "• When requesting table format, pass the individual scores to the Composite Scorer Agent."
    ),
    tools=[],
)