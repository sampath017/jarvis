# Javris: Your Personal Agentic Assistant 🤖

Javris is a high-performance, bidirectional AI assistant designed to manage your life via persistent chat. Unlike traditional bots, Javris is built using **LangGraph**, allowing it to "think," use tools, and maintain a stateful memory of your tasks and notes.

## 🌟 Key Features
- **Persistent Chat UI**: Fluid, glassmorphic chat interface that overlays your workspace.
- **Agentic Logic**: Built with LangGraph for complex tool-chaining and decision making.
- **Smart Task Management**: Add, update, and delete tasks with natural language.
- **Contextual Note Merging**: Javris automatically checks for duplicate notes and asks to merge them.
- **Stateful Memory**: Remembers your conversation thread history across multiple prompts.
- **Observability**: Integrated with LangSmith for real-time tracing of AI "thoughts."

---

## 🏗️ Project Structure
- `jarvis_mobile/`: Flutter mobile application (Frontend).
- `jarvis_backend/`: FastAPI & LangGraph service (Backend).

---

## 🚀 Getting Started

### 1. Backend Setup (FastAPI + LangGraph)
The backend acts as the "Brain" of Javris.

**Prerequisites:**
- Python 3.10+
- A Google AI Studio API Key (Gemini 3 Flash or higher recommended)

**Steps:**
1. Navigate to the backend directory:
   ```bash
   cd jarvis_backend
   ```
2. Create a virtual environment and install dependencies:
   ```bash
   uv install
   ```
3. Configure your `.env` file:
   Create a `.env` file in the `jarvis_backend/` root:
   ```env
   GOOGLE_API_KEY=your_gemini_api_key
   
   # Required for Memory persistence
   THREAD_ID="javris_user_1"

   # Optional: For tracing your AI's thoughts
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
   LANGCHAIN_API_KEY=your_langsmith_key
   LANGCHAIN_PROJECT="Javris-Mobile-Backend"
   ```
4. Run the server using uv:
   ```bash
   uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
   ```

### 2. Frontend Setup (Flutter)
The frontend is the "Face" of Javris.

**Prerequisites:**
- Flutter SDK (latest stable)
- Firebase Project setup

**Steps:**
1. Navigate to the mobile directory:
   ```bash
   cd jarvis_mobile
   ```
2. Install dependencies:
   ```bash
   flutter pub get
   ```
3. Connect Firebase:
   - Place your `google-services.json` (Android) or `GoogleService-Info.plist` (iOS) in the appropriate directories.
   - Ensure Firestore is enabled in the Firebase Console.
4. Run the app:
   ```bash
   flutter run
   ```

---

## ⚙️ Configuration & Firebase
Javris uses **Cloud Firestore** as its database.
- **Collections Required**: `tasks` and `notes`.
- **Backend Auth**: Ensure you have your Firebase Service Account JSON file and its path is correctly configured in `src/firebase_config.py`.

---

## 🛠️ Technology Stack
- **Frontend**: Flutter, Riverpod 3.x (State Management).
- **Backend**: Python, FastAPI, LangGraph (Agentic Framework).
- **AI Model**: `gemini-1.5-flash` (via Google AI Studio).
- **Observability**: LangSmith (for tracing and debugging).

---

## ⚖️ Safety & Optimization
This project includes built-in safety nets:
- **Recursion Limit**: Prevents infinite loops in agent logic (Default: 15).
- **Merge-First Policy**: AI is instructed to avoid creating duplicate notes.
- **Memory Saver**: Built-in stateless checkpointing for persistent conversation context.

---

## 📜 License
This project is for personal use and development exploration. Enjoy building your own Jarvis!
