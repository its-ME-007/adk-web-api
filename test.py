from vertexai import agent_engines
import vertexai
import asyncio # Import asyncio for running async code

# Initialize Vertex AI
PROJECT_ID = "image-gen-34b6b"
LOCATION = "us-central1"
vertexai.init(project=PROJECT_ID, location=LOCATION)

# Load Agent Engine
AGENT_ENGINE_RESOURCE_NAME = "projects/948832582788/locations/us-central1/reasoningEngines/7816041133766606848"

async def main():
    try:
        print(f"Loading Agent Engine: {AGENT_ENGINE_RESOURCE_NAME}")
        agent_engine = agent_engines.get(AGENT_ENGINE_RESOURCE_NAME) # Use await here
        print("Agent Engine loaded successfully.")

        # Create a new session for the conversation
        print("Creating a new session...")
        session = await agent_engine.create_session(user_id="test_user_123") # Use await here

        # Access session details
        print(f"Session created with ID: {session['id']}")

        # Send a message within the session
        print(f"Sending query to session {session['id']}...")
        prompt = "Hello, what can you do?"

        async for event in agent_engine.stream_query( # stream_query is also likely async
            user_id="test_user_123",
            session_id=session['id'],
            message=prompt,
        ):
            if 'messages' in event:
                for message in event['messages']:
                    print(f"Agent Message ({message['role']}): {message['text']}")
            elif 'output' in event:
                print(f"Final Output: {event['output']}")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())