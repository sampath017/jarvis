import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv
from .logger import logger

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
            firebase_admin.initialize_app(options={'projectId': 'gen-lang-client-0513238373'})
        return firestore.client(database_id='jarvis')
    except Exception as e:
        logger.error(f"Firebase Initialization Failed: {e}")
        logger.info("Run 'gcloud auth application-default login' or place your service-account.json in the jarvis_backend folder.")
        raise e

db = initialize_firebase()
