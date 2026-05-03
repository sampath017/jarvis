import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from src.mcp_server import add_task, list_tasks, add_note, list_notes
from src.agent import run_agent

from contextlib import asynccontextmanager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
import src.mcp_registry as mcp_registry

mcp_session_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_session_manager
    print("Initializing Google Tools MCP Server connection...")
    try:
        # Use .cmd for Windows global npm packages
        server_params = StdioServerParameters(command="google-tools-mcp.cmd", args=[])
        stdio_ctx = stdio_client(server_params)
        read, write = await stdio_ctx.__aenter__()
        
        session_ctx = ClientSession(read, write)
        session = await session_ctx.__aenter__()
        
        await session.initialize()
        all_tools = await load_mcp_tools(session)
        # Filter tools to prevent Gemini strict schema errors (e.g. from complex Sheets tools) 
        # and to focus on the user's explicit needs (Calendar only)
        allowed_keywords = ['calendar', 'event']
        mcp_registry.mcp_tools_list = [
            t for t in all_tools
            if any(k in t.name.lower() for k in allowed_keywords)
        ]
        
        print(f"Filtered to {len(mcp_registry.mcp_tools_list)} safe MCP tools: {[t.name for t in mcp_registry.mcp_tools_list]}")
        
        mcp_session_manager = (stdio_ctx, session_ctx)
    except Exception as e:
        print(f"Failed to initialize MCP Server: {e}")
        
    yield
    
    if mcp_session_manager:
        stdio_ctx, session_ctx = mcp_session_manager
        await session_ctx.__aexit__(None, None, None)
        await stdio_ctx.__aexit__(None, None, None)

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
async def ask_javris(request: ChatRequest):
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
        print(f"ERROR IN BACKEND: {str(e)}")
        import traceback
        traceback.print_exc()
        traceback.print_exc()
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
        print(f"ERROR IN FEEDBACK: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Firestore Crud Fallbacks (optional, since Flutter app talks to Firestore directly) ---

@app.get("/health")
async def health():
    return {"status": "ok", "service": "javris-backend"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
