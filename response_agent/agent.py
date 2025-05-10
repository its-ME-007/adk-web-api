# --- Import necessary libraries ---
from google.adk.agents import LlmAgent, Agent, SequentialAgent, ParallelAgent
from google.adk.sessions import DatabaseSessionService  # Correct import
import os
import psycopg2

# --- Database Connection Details (Using Environment Variable for Security) ---
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("Warning: DATABASE_URL environment variable not set. Database functionality will be limited.")

# --- Tool Definition: Save Response to File and Database ---
def save_response_to_file_and_db(response_content: str, agent_name: str) -> str:
    """
    Writes the provided response content from a specific agent to a dedicated file and saves it to the database.
    
    Args:
        response_content (str): The actual text content of the response to be saved.
        agent_name (str): The name of the agent (e.g., 'CEO', 'Senior_Manager', 'Specialist')
                          whose response is being saved. This determines the filename and the database record.

    Returns:
        str: A confirmation message indicating the file path where the response was saved or an error message.
    """
    safe_agent_name = "".join(c if c.isalnum() else "_" for c in agent_name)
    filename = f"wanted_response_{safe_agent_name.lower()}.txt"

    try:
        # Save the response to a file
        with open(filename, "a", encoding="utf-8") as f:
            f.write(f"--- Response from {agent_name} ---\n")
            f.write(response_content)
            f.write("\n\n")
        
        # Insert the response into the database
        if DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO agent_responses (agent_name, response_content) VALUES (%s, %s)",
                (agent_name, response_content)
            )
            conn.commit()
            conn.close()

        return f"Successfully saved response from {agent_name} to {filename} and database."
    
    except Exception as e:
        return f"Error saving response from {agent_name} to {filename} and database: {str(e)}"

# --- Tool Definition: Get Industry Insight from Database ---
def get_industry_insight(industry: str) -> str:
    """
    Retrieves the most recent agent response related to a given industry.
    """
    if not DATABASE_URL:
        return "Database connection details not available."

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        query = """
            SELECT agent_name, response_content, created_at
            FROM agent_responses
            WHERE response_content ILIKE %s
            ORDER BY created_at DESC
            LIMIT 1;
        """
        cursor.execute(query, (f"%{industry}%",))
        result = cursor.fetchone()
        conn.close()

        if result:
            agent_name, response, created_at = result
            return f"🧠 Latest insight from {agent_name} on '{industry}' (at {created_at}):\n\n{response}"
        else:
            return f"No relevant insights found for industry: {industry}"

    except Exception as e:
        return f"❌ Error fetching industry insight: {str(e)}"


# --- Agent Definitions (Parallel Agents) ---
agent_ceo_parallel = LlmAgent(
    name="CEO",
    model="gemini-2.0-flash-exp",
    description="The Chief Executive Officer...",
    instruction="As the CEO, you operate at the highest strategic level. When responding to user queries about setting up an industry, consider the long-term implications, market positioning, and overall business strategy. Focus on high-level considerations like investment, scalability, and competitive advantages. You can also use the 'get_industry_insight' tool if the user asks for a specific industry insight.",
    output_key="ceo_response",
    tools=[get_industry_insight],  # Passing the function directly as a tool
)

agent_senior_manager_parallel = LlmAgent(
    name="Senior_Manager",
    model="gemini-2.0-flash-exp",
    description="A seasoned Senior Manager...",
    instruction="As a Senior Manager, you bridge the gap between strategy and execution. When addressing user questions about setting up an industry, focus on operational aspects, supply chain considerations, regulatory requirements, and potential challenges in implementation.",
    output_key="manager_response",
)

agent_specialist_parallel = LlmAgent(
    name="Specialist",
    model="gemini-2.0-flash-exp",
    description="A highly skilled subject matter expert...",
    instruction="As a Specialist in manufacturing, when responding to user inquiries about setting up an industry, provide detailed information on raw material sourcing, processing techniques, quality control, local expertise availability, and any specific technical considerations relevant to raw material production in that region.",
    output_key="specialist_response",
)

gather_concurrently = ParallelAgent(
    name="ConcurrentFetch",
    sub_agents=[agent_ceo_parallel, agent_senior_manager_parallel, agent_specialist_parallel],
)

# --- Root Agent Definition ---
root_agent = Agent(
    name="DisplayAndSaveAgent",
    model="gemini-2.0-flash-exp",
    sub_agents=[gather_concurrently],
    description="This agent gathers information from CEO, Manager, and Specialist sub-agents, displays it, and saves specific responses to files and the database upon user request.",
    instruction=(
        "Your primary role is to orchestrate the information flow and interact with the user.\n"
        "1. First, execute the 'ConcurrentFetch' parallel agent. This will run the CEO, Senior_Manager, and Specialist agents. Their responses will be available in your context under the keys 'ceo_response', 'manager_response', and 'specialist_response'.\n"
        "2. Once you have the responses, synthesize and present them clearly to the user. Use bullet points or distinct sections, clearly indicating which response came from which agent (e.g., 'CEO Perspective:', 'Senior Manager Insights:', 'Specialist Details:').\n"
        "3. After presenting the information, explicitly ask the user if they would like to save the response from any specific agent (e.g., 'Would you like me to save the response from the CEO, Senior Manager, or Specialist?').\n"
        "4. **If and only if** the user confirms they want to save a response and specifies which one (e.g., 'Yes, save the CEO response', 'Save the manager's part'):**\n"
        "   a. Identify the target agent name ('CEO', 'Senior_Manager', or 'Specialist').\n"
        "   b. Retrieve the *complete text* of that agent's response from your context using the corresponding key ('ceo_response', 'manager_response', or 'specialist_response').\n"
        "   c. Call the `save_response_to_file_and_db` tool. \n"
        "   d. Pass the retrieved text as the `response_content` argument.\n"
        "   e. Pass the identified agent name (e.g., 'CEO') as the `agent_name` argument.\n"
        "   f. Report the outcome (success or error message returned by the tool) back to the user.\n"
        "5. **Crucially: Do NOT run the 'ConcurrentFetch' agent again just to save a file.** Use the responses you already obtained in step 1.\n"
        "6. If the user asks a follow-up question or provides a new query not related to saving, handle it appropriately, potentially by re-running 'ConcurrentFetch' if new perspectives are needed for a *new* topic. Be aware that the CEO agent has access to the 'get_industry_insight' tool if the user asks for specific industry insights."
    ),
    tools=[save_response_to_file_and_db],  # Passing the function directly as a tool
)
