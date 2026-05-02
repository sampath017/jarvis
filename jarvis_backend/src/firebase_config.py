import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv

load_dotenv()

def initialize_firebase():
    try:
        # 1. Try to load from a local service account file if it exists
        cred_path = os.path.join(os.path.dirname(__file__), "..", "service-account.json")
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)
            return firestore.client()
        
        # 2. Fallback to Application Default Credentials (ADC)
        if not firebase_admin._apps:
            # Explicitly set the project ID to avoid mismatch with ADC quota project
            firebase_admin.initialize_app(options={'projectId': 'jarvis-tasks-backend'})
        return firestore.client()
    except Exception as e:
        print(f"\n[ERROR] Firebase Initialization Failed: {e}")
        print("[TIP] Run 'gcloud auth application-default login' or place your service-account.json in the jarvis_backend folder.\n")
        raise e

db = initialize_firebase()
