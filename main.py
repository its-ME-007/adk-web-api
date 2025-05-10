import os
import json
import asyncio
from pathlib import Path
from typing import AsyncIterator # For type hinting async iterators

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.websockets import WebSocketState # Moved import to top level

from google.genai.types import Part, Content
# Assuming Event is a type provided by ADK, e.g., from google.adk.events
# from google.adk.events import Event # Example import for Event type

from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig
from google.adk.sessions.in_memory_session_service import InMemorySessionService

from response_agent.agent import root_agent # Your custom agent

# Load Gemini API Key
load_dotenv()

APP_NAME = "ADK Streaming Example (Async Event Model)"
session_service = InMemorySessionService() # Global session service

# --- Agent Resource Setup ---
def setup_agent_resources_for_session(client_session_id_str: str):
    """
    Creates and returns the necessary ADK resources for an agent session.
    The session_obj is created and managed by the session_service.
    The runner will use user_id and session_id to interact with it.
    """
    print(f"Setting up ADK resources for session: {client_session_id_str}")
    # Create and register the Session object with the service
    session_obj = session_service.create_session(
        app_name=APP_NAME,
        user_id=client_session_id_str,
        session_id=client_session_id_str,
    )

    runner = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        session_service=session_service, # Runner uses this service
    )

    run_config = RunConfig(response_modalities=["TEXT"])

    # Return the created session_obj if needed elsewhere,
    # but runner.run_async will use IDs to find it via session_service.
    # For this pattern, we primarily need runner and run_config for the endpoint.
    # The session_obj's existence in session_service is what matters.
    return runner, run_config, session_obj # Returning session_obj in case it's needed for explicit cleanup later

# --- Agent Event Processing (same as before) ---
async def process_and_send_agent_events(websocket: WebSocket, turn_event_stream: AsyncIterator): # Replace AsyncIterator with AsyncIterator[Event] if Event type is known
    """
    Processes an event stream for a single agent turn and sends messages to the client.
    """
    current_message_buffer = ""
    print("[PROCESS EVENTS] Starting to process event stream for a turn.")
    try:
        async for event in turn_event_stream: # Iterate over the events for the current turn
            if hasattr(event, 'turn_complete') and event.turn_complete:
                if current_message_buffer:
                    await websocket.send_text(json.dumps({"message": current_message_buffer}))
                    print(f"[AGENT TO CLIENT - FULL TURN]: {current_message_buffer}")
                    current_message_buffer = ""
                await websocket.send_text(json.dumps({"turn_complete": True}))
                print("[TURN COMPLETE]")
                return

            if hasattr(event, 'interrupted') and event.interrupted:
                if current_message_buffer:
                    await websocket.send_text(json.dumps({"message": current_message_buffer}))
                    print(f"[AGENT TO CLIENT - PARTIAL/INTERRUPTED]: {current_message_buffer}")
                    current_message_buffer = ""
                await websocket.send_text(json.dumps({"interrupted": True, "turn_complete": True}))
                print("[INTERRUPTED]")
                return

            event_content = getattr(event, 'content', None)
            is_partial = getattr(event, 'partial', False)
            
            if event_content and event_content.parts and is_partial:
                part = event_content.parts[0]
                if hasattr(part, 'text') and part.text:
                    text_chunk = part.text
                    current_message_buffer += text_chunk
            await asyncio.sleep(0)

        if current_message_buffer:
            await websocket.send_text(json.dumps({"message": current_message_buffer, "turn_complete": True}))
            print(f"[AGENT TO CLIENT - END OF STREAM BUFFER]: {current_message_buffer}")
        else:
            await websocket.send_text(json.dumps({"turn_complete": True}))
            print("[PROCESS EVENTS] Event stream ended, ensuring turn_complete sent.")

    except WebSocketDisconnect:
        print("[PROCESS EVENTS] WebSocket disconnected while processing agent events.")
        raise
    except Exception as e:
        print(f"Error in process_and_send_agent_events: {e}")
        try:
            if websocket.client_state != WebSocketState.DISCONNECTED:
                await websocket.send_text(json.dumps({"error": str(e), "turn_complete": True}))
        except Exception:
            print("[PROCESS EVENTS] Could not send error to client, WebSocket likely closed.")


# --- FastAPI Application (Static files and root path same as before) ---
app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static"
if not STATIC_DIR.exists(): STATIC_DIR.mkdir(parents=True, exist_ok=True) # Simplified
if not (STATIC_DIR / "index.html").exists():
    with open(STATIC_DIR / "index.html", "w") as f: f.write("<html><body><h1>ADK Agent Test</h1><div id='output'></div><input id='input' type='text'><button onclick='sendMsg()'>Send</button><script>const ws = new WebSocket(`ws://${location.host}/ws/testclient` + Math.random());const output = document.getElementById('output');ws.onmessage = event => {const p = document.createElement('p');p.textContent = event.data;output.appendChild(p);}; ws.onopen = () => output.innerHTML = '<p>Connected!</p>'; ws.onclose = () => output.innerHTML += '<p>Disconnected!</p>'; function sendMsg(){ws.send(document.getElementById('input').value);document.getElementById('input').value='';}</script></body></html>")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def get_root_page():
    index_html_path = STATIC_DIR / "index.html"
    return FileResponse(index_html_path) if index_html_path.is_file() else ({"error": "index.html not found"}, 404)

@app.websocket("/ws/{client_session_id}")
async def websocket_endpoint(websocket: WebSocket, client_session_id: str):
    await websocket.accept()
    print(f"Client #{client_session_id} connected via WebSocket.")

    runner, run_config, session_obj_for_cleanup = None, None, None # session_obj_for_cleanup to hold the session object if needed for explicit cleanup
    try:
        runner, run_config, session_obj_for_cleanup = setup_agent_resources_for_session(client_session_id)

        while True:
            user_text = await websocket.receive_text()
            print(f"[CLIENT ({client_session_id}) TO SERVER]: {user_text}")

            user_content = Content(role="user", parts=[Part.from_text(text=user_text)])

            print(f"Invoking agent for session {client_session_id} with new message...")
            turn_event_stream = runner.run_async(
                user_id=client_session_id,    # Pass user_id string
                session_id=client_session_id, # Pass session_id string
                new_message=user_content,
                run_config=run_config
            )
            # This assumes run_async called with user_id/session_id returns only the event stream,
            # which aligns with the previous "cannot unpack non-iterable async_generator object" error
            # when it was expected to return a tuple.

            await process_and_send_agent_events(websocket, turn_event_stream)
            print(f"Finished processing agent response for session {client_session_id}.")

    except WebSocketDisconnect:
        print(f"Client #{client_session_id} disconnected.")
    except Exception as e:
        error_message = f"Unhandled error in websocket_endpoint for client #{client_session_id}: {type(e).__name__} - {e}"
        print(error_message)
        try:
            # WebSocketState is now globally imported
            if websocket.client_state != WebSocketState.DISCONNECTED:
                 await websocket.send_text(json.dumps({"error": error_message, "turn_complete": True}))
        except Exception as send_error:
            # This will now print the actual send_error if it occurs
            print(f"Could not send final error to client #{client_session_id}: {type(send_error).__name__} - {send_error}")
    finally:
        print(f"Closing connection processing for client #{client_session_id}.")
        # Optional: Explicitly clean up the session if your service requires it
        # if session_obj_for_cleanup and hasattr(session_service, 'delete_session'):
        #     try:
        #         # Ensure you have a method like delete_session in your InMemorySessionService
        #         # or use the appropriate method from ADK if available
        #         session_service.delete_session(session_id=session_obj_for_cleanup.session_id)
        #         print(f"Cleaned up session {session_obj_for_cleanup.session_id}")
        #     except Exception as cleanup_error:
        #         print(f"Error during session cleanup for {session_obj_for_cleanup.session_id}: {cleanup_error}")
        
        try:
            if websocket.client_state != WebSocketState.DISCONNECTED:
                await websocket.close()
                print(f"WebSocket closed for client #{client_session_id}.")
        except Exception as close_exc:
             print(f"Exception while trying to close WebSocket for client #{client_session_id}: {close_exc}")