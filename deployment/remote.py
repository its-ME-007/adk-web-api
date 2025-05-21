import os
import sys
import logging

import vertexai
from absl import app, flags
from dotenv import load_dotenv
from vertexai import agent_engines
from vertexai.preview import reasoning_engines
from repeat.agent import root_agent

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create a file handler and a stream handler
file_handler = logging.FileHandler('deployment.log')
stream_handler = logging.StreamHandler()

# Create a formatter and set it for the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# Define flags for command-line arguments (keep this section only once)
FLAGS = flags.FLAGS
flags.DEFINE_string("project_id", None, "GCP project ID.")
flags.DEFINE_string("location", None, "GCP location.")
flags.DEFINE_string("bucket", None, "GCP bucket.")
flags.DEFINE_string("resource_id", None, "ReasoningEngine resource ID (for delete, get_session, send).")
flags.DEFINE_string("user_id", "test_user", "User ID for session operations.")
flags.DEFINE_string("session_id", None, "Session ID for operations (for get_session, send).")
flags.DEFINE_bool("create", False, "Creates a new deployment.")
flags.DEFINE_bool("delete", False, "Deletes an existing deployment.")
flags.DEFINE_bool("list", False, "Lists all deployments.")
flags.DEFINE_bool("create_session", False, "Creates a new session.")
flags.DEFINE_bool("list_sessions", False, "Lists all sessions for a user.")
flags.DEFINE_bool("get_session", False, "Gets a specific session.")
flags.DEFINE_bool("send", False, "Sends a message to the deployed agent.")
flags.DEFINE_string(
    "message",
    "Hello, what can you do?", # Default message
    "Message to send to the agent.",
)
# Flags for Firebase Secret Manager
flags.DEFINE_string("firebase_secret_id", None, "Secret Manager Secret ID for Firebase credentials.")
flags.DEFINE_string("firebase_secret_version", None, "Secret Manager Secret Version for Firebase credentials.")

# Ensure only one action flag is set
flags.mark_bool_flags_as_mutual_exclusive(
    [
        "create",
        "delete",
        "list",
        "create_session",
        "list_sessions",
        "get_session",
        "send",
    ]
)


def create() -> None:
    """Creates a new deployment."""
    try:
        logger.info("Successfully imported root_agent.")
    except ImportError as e:
        logger.error(f"Error importing root_agent: {e}")
        logger.error("Please ensure your 'repeat' directory is structured correctly and contains agent.py.")
        return

    app = reasoning_engines.AdkApp(
        agent=root_agent,
        enable_tracing=True,
    )

    required_packages = [
        "google-cloud-aiplatform[adk,agent_engines]",
        "firebase_admin",
        "google-cloud-firestore",
        "google-cloud-secret-manager",
        "python-dotenv", 
        "absl-py", 
        "cloudpickle",
        "pydantic", 
        
    ]
    logger.info("Creating AgentEngine deployment...")
    remote_app = agent_engines.create(
        agent_engine=app,
        requirements=required_packages,
        extra_packages=["./repeat"], # This includes your agent code and local dependencies
        # Set environment variables for the deployed agent to access Secret Manager
    )

    logger.info(f"AgentEngine deployment created: {remote_app.resource_name}")
    print(f"AgentEngine deployment created: {remote_app.resource_name}")
    print(f"View progress and logs at https://console.cloud.google.com/logs/query?project={FLAGS.project_id}&resource=aiplatform.googleapis.com%2FreasoningEngine%2F{remote_app.resource_name.split('/')[-1]}")


def delete(resource_name: str) -> None:
    """Deletes an existing deployment."""
    try:
        logger.info(f"Deleting remote app: {resource_name}")
        remote_app = agent_engines.get(resource_name)
        remote_app.delete(force=True)
        print(f"Deleted remote app: {resource_name}")
    except Exception as e:
        logger.error(f"Error deleting remote app {resource_name}: {e}")
        print(f"Error deleting remote app {resource_name}: {e}")


def list_deployments() -> None:
    """Lists all deployments."""
    try:
        logger.info("Listing deployments...")
        deployments = agent_engines.list()
        if not deployments:
            print("No deployments found.")
            return
        print("Deployments:")
        for deployment in deployments:
            print(f"- {deployment.resource_name}")
    except Exception as e:
        logger.error(f"Error listing deployments: {e}")
        print(f"Error listing deployments: {e}")


def create_session(resource_name: str, user_id: str) -> None:
    """Creates a new session for the specified user."""
    try:
        logger.info(f"Creating session for deployment: {resource_name}")
        remote_app = agent_engines.get(resource_name)
        remote_session = remote_app.create_session(user_id=user_id)
        # Access session details using dictionary keys
        print("Created session:")
        print(f"  Session ID: {remote_session.get('id')}")
        print(f"  User ID: {remote_session.get('user_id')}")
        print(f"  App name: {remote_session.get('app_name')}")
        print(f"  Last update time: {remote_session.get('last_update_time')}")
        print("\nUse this session ID with --session_id when sending messages.")
    except Exception as e:
        logger.error(f"Error creating session for {resource_name}: {e}")
        print(f"Error creating session for {resource_name}: {e}")


def list_sessions(resource_name: str, user_id: str) -> None:
    """Lists all sessions for the specified user."""
    try:
        logger.info(f"Listing sessions for user '{user_id}' on deployment: {resource_name}")
        remote_app = agent_engines.get(resource_name)
        sessions = remote_app.list_sessions(user_id=user_id)
        print(f"Sessions for user '{user_id}':")
        if sessions:
            for session in sessions:
                 print(f"- Session ID: {session.get('id')}")
        else:
            print("No sessions found for this user.")
    except Exception as e:
        logger.error(f"Error listing sessions for {resource_name}: {e}")
        print(f"Error listing sessions for {resource_name}: {e}")


def get_session(resource_name: str, user_id: str, session_id: str) -> None:
    """Gets a specific session."""
    try:
        logger.info(f"Getting session {session_id} for user '{user_id}' on deployment: {resource_name}")
        remote_app = agent_engines.get(resource_name)
        session = remote_app.get_session(user_id=user_id, session_id=session_id)
        print("Session details:")
        print(f"  ID: {session.get('id')}")
        print(f"  User ID: {session.get('user_id')}")
        print(f"  App name: {session.get('app_name')}")
        print(f"  Last update time: {session.get('last_update_time')}")
    except Exception as e:
        logger.error(f"Error getting session {session_id} for {resource_name}: {e}")
        print(f"Error getting session {session_id} for {resource_name}: {e}")


def send_message(resource_name: str, user_id: str, session_id: str, message: str) -> None:
    """Sends a message to the deployed agent."""
    try:
        logger.info(f"Sending message to session {session_id} on deployment: {resource_name}")
        print(f"Sending message to session {session_id} on deployment: {resource_name}")
        print(f"Message: {message}")
        remote_app = agent_engines.get(resource_name)

        print("\nResponse (streaming):")
        # Ensure you handle the event structure from stream_query based on your agent's output
        for event in remote_app.stream_query(
            user_id=user_id,
            session_id=session_id,
            message=message,
        ):
            # Example: Printing messages and output (adjust based on actual event structure)
            if 'messages' in event:
                 for msg in event['messages']:
                      # Print role if available, otherwise just the text
                      role_prefix = f"({msg.get('role')}): " if msg.get('role') else ""
                      print(f"Agent Message {role_prefix}{msg.get('text', '')}")
            elif 'output' in event:
                 print(f"Final Output: {event['output']}")
            elif 'actions' in event:
                 print(f"Agent Actions: {event['actions']}")
            else:
                 # Print any other event structure for debugging
                 print(f"Received event: {event}")

    except Exception as e:
        logger.error(f"An error occurred while sending message to {resource_name}: {e}")
        print(f"An error occurred while sending message to {resource_name}: {e}")


def main(argv=None):
    """Main function that can be called directly or through app.run()."""
    # Parse flags first
    if argv is None:
        argv = flags.FLAGS(sys.argv)
    else:
        argv = flags.FLAGS(argv)

    # Load environment variables from .env file
    load_dotenv()

    # Access the flags or environment variables
    project_id = FLAGS.project_id if FLAGS.project_id else os.getenv("GOOGLE_CLOUD_PROJECT")
    location = FLAGS.location if FLAGS.location else os.getenv("GOOGLE_CLOUD_LOCATION")
    bucket = FLAGS.bucket if FLAGS.bucket else os.getenv("GOOGLE_CLOUD_STAGING_BUCKET")
    user_id = FLAGS.user_id
    resource_name = FLAGS.resource_id # Use resource_name for consistency

    # Validate required configuration
    if not project_id:
        logger.error("Error: Missing required configuration. Please provide --project_id flag or set GOOGLE_CLOUD_PROJECT environment variable.")
        print("Error: Missing required configuration.")
        print("Please provide --project_id flag or set GOOGLE_CLOUD_PROJECT environment variable.")
        return
    elif not location:
        logger.error("Error: Missing required configuration. Please provide --location flag or set GOOGLE_CLOUD_LOCATION environment variable.")
        print("Error: Missing required configuration.")
        print("Please provide --location flag or set GOOGLE_CLOUD_LOCATION environment variable.")
        return
    elif not bucket:
        logger.error("Error: Missing required configuration. Please provide --bucket flag or set GOOGLE_CLOUD_STAGING_BUCKET environment variable.")
        print("Error: Missing required configuration.")
        print("Please provide --bucket flag or set GOOGLE_CLOUD_STAGING_BUCKET environment variable.")
        return

    # Initialize Vertex AI SDK
    logger.info(f"Initializing Vertex AI for project '{project_id}' in location '{location}' using bucket '{bucket}'...")
    print(f"Initializing Vertex AI for project '{project_id}' in location '{location}' using bucket '{bucket}'...")
    vertexai.init(
        project=project_id,
        location=location,
        staging_bucket=bucket,
    )
    logger.info("Vertex AI initialized.")
    print("Vertex AI initialized.")

    # Execute the requested action
    if FLAGS.create:
        create()
    elif FLAGS.delete:
        if not resource_name:
            logger.error("Error: resource_id is required for delete. Provide --resource_id.")
            print("Error: resource_id is required for delete. Provide --resource_id.")
            return
        delete(resource_name)
    elif FLAGS.list:
        list_deployments()
    elif FLAGS.create_session:
        if not resource_name:
            logger.error("Error: resource_id is required for create_session. Provide --resource_id.")
            print("Error: resource_id is required for create_session. Provide --resource_id.")
            return
        create_session(resource_name, user_id)
    elif FLAGS.list_sessions:
        if not resource_name:
            logger.error("Error: resource_id is required for list_sessions. Provide --resource_id.")
            print("Error: resource_id is required for list_sessions. Provide --resource_id.")
            return
        list_sessions(resource_name, user_id)
    elif FLAGS.get_session:
        if not resource_name:
            logger.error("Error: resource_id is required for get_session. Provide --resource_id.")
            print("Error: resource_id is required for get_session. Provide --resource_id.")
            return
        if not FLAGS.session_id:
            logger.error("Error: session_id is required for get_session. Provide --session_id.")
            print("Error: session_id is required for get_session. Provide --session_id.")
            return
        get_session(resource_name, user_id, FLAGS.session_id)
    elif FLAGS.send:
        if not resource_name:
            logger.error("Error: resource_id is required for send. Provide --resource_id.")
            print("Error: resource_id is required for send. Provide --resource_id.")
            return
        if not FLAGS.session_id:
            logger.error("Error: session_id is required for send. Provide --session_id.")
            print("Error: session_id is required for send. Provide --session_id.")
            return
        send_message(resource_name, user_id, FLAGS.session_id, FLAGS.message)
    else:
        print(
            "Please specify one of the action flags: --create, --delete, --list, --create_session, --list_sessions, --get_session, or --send"
        )
        print("\nExample for creation:")
        print("  poetry run python deployment/remote.py --create --project_id=<your-project-id> --location=<your-location> --bucket=<your-bucket-name> --firebase_secret_id=<your-secret-id>")


if __name__ == "__main__":
    # app.run() handles parsing flags and calling main
    app.run(main)