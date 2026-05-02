import asyncio
import os
import sys
from dotenv import load_dotenv

# Add src to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

load_dotenv()

from src.agent import run_agent

async def test():
    print("Testing Agent...")
    try:
        response = await run_agent("What tasks do I have?")
        print(f"Response: {response}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
