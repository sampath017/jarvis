import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from src.mcp_server import add_task, list_tasks, add_note, list_notes
from src.agent import run_agent

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str

@app.post("/ask", response_model=ChatResponse)
async def ask_javris(request: ChatRequest):
    try:
        response = await run_agent(request.message)
        return ChatResponse(response=response)
    except Exception as e:
        print(f"ERROR IN BACKEND: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# --- Firestore Crud Fallbacks (optional, since Flutter app talks to Firestore directly) ---

@app.get("/health")
async def health():
    return {"status": "ok", "service": "javris-backend"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
