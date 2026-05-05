import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from dotenv import load_dotenv
load_dotenv()
from .logger import logger
from src.mcp_server import add_task, list_tasks, add_note, list_notes
from src.agent import run_agent

from contextlib import asynccontextmanager
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
import src.mcp_registry as mcp_registry

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.mcp_session = None
    mcp_registry.mcp_tools_list = []

    async def init_mcp():
        logger.info("Initializing Google Tools MCP Server in background...")
        try:
            server_params = StdioServerParameters(
                command="google-tools-mcp",
                env={**os.environ}
            )
            logger.info("Connecting to MCP server...")
            async with stdio_client(server_params) as (read, write):
                logger.info("Stdio connection established. Starting session...")
                async with ClientSession(read, write) as session:
                    async with asyncio.timeout(180): # Timeout only applies to handshake
                        logger.info("Initializing session...")
                        await session.initialize()
                        logger.info("Session initialized. Loading tools...")
                        
                        # Load and register tools
                        all_tools = await load_mcp_tools(session)
                        allowed_keywords = ['calendar', 'event']
                        mcp_registry.mcp_tools_list = [
                            t for t in all_tools
                            if any(k in t.name.lower() for k in allowed_keywords)
                        ]
                        
                        logger.info(f"✅ MCP ready with {len(mcp_registry.mcp_tools_list)} tools.")
                        app.state.mcp_session = session
                    
                    # Keep session alive indefinitely after successful init
                    await asyncio.Event().wait()
        except asyncio.CancelledError:
            logger.info("MCP initialization background task cancelled.")
        except asyncio.TimeoutError:
            logger.error("❌ MCP initialization timed out.")
        except Exception as e:
            logger.error(f"❌ MCP initialization failed: {e}")
            import traceback
            logger.error(traceback.format_exc())

    # Start MCP in the background
    mcp_task = asyncio.create_task(init_mcp())

    yield  # ← Server is live here, port 8080 is bound immediately ✅

    # Shutdown
    logger.info("Shutting down... cancelling MCP task.")
    mcp_task.cancel()
    try:
        await mcp_task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "javris_user_1"
    thread_title: str = "Chat Session"
    user_latitude: float = None
    user_longitude: float = None

class ChatResponse(BaseModel):
    response: str

@app.post("/ask", response_model=ChatResponse)
async def ask_agent(request: ChatRequest):
    logger.info(f"Received request on /ask: {request.message[:50]}...")
    try:
        response = await run_agent(
            request.message, 
            request.thread_id, 
            request.thread_title,
            user_latitude=request.user_latitude,
            user_longitude=request.user_longitude
        )
        return ChatResponse(response=response)
    except Exception as e:
        logger.error(f"ERROR IN BACKEND: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

class FeedbackRequest(BaseModel):
    thread_id: str
    score: int

@app.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    try:
        from langfuse import Langfuse
        client = Langfuse()
        client.score(
            session_id=request.thread_id,
            name="user_feedback",
            value=request.score,
            comment="Thumbs feedback from mobile UI"
        )
        client.flush()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"ERROR IN FEEDBACK: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Firestore Crud Fallbacks (optional, since Flutter app talks to Firestore directly) ---

@app.get("/health")
async def health():
    return {"status": "ok", "service": "javris-backend"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
