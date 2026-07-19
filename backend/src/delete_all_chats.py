import sys
import os
from services.firestore_client import init_firebase, get_firestore_client

def main():
    print("Initializing Firebase...")
    try:
        # Load custom/default credentials path from environment
        project_id = os.getenv("FIREBASE_PROJECT_ID", "jarvis-agent-61947")
        init_firebase(project_id)
        db = get_firestore_client()
        print(f"Firebase initialized for project: {project_id}. Fetching users...")
        
        users_ref = db.collection("users")
        users = list(users_ref.stream())
        print(f"Found {len(users)} user(s) in the database.")
        
        total_threads_deleted = 0
        
        for user in users:
            uid = user.id
            print(f"Processing user: {uid}")
            threads_ref = users_ref.document(uid).collection("chatThreads")
            threads = list(threads_ref.stream())
            print(f"  Found {len(threads)} chat thread(s) for user {uid}")
            
            for thread in threads:
                thread_id = thread.id
                print(f"    Deleting messages in thread: {thread_id}")
                
                # Delete messages subcollection documents first
                messages_ref = threads_ref.document(thread_id).collection("messages")
                messages = list(messages_ref.stream())
                for message in messages:
                    message.reference.delete()
                
                # Delete thread document itself
                thread.reference.delete()
                total_threads_deleted += 1
                print(f"    Deleted thread {thread_id} and all its messages.")
                
        print(f"Successfully deleted {total_threads_deleted} chat threads in total.")
    except Exception as e:
        print(f"Error executing chat cleanup: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
