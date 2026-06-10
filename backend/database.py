from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
if not mongo_uri:
    mongo_uri = "mongodb://localhost:27017"

client = AsyncIOMotorClient(mongo_uri)
db = client["chatbot_db"]
messages_collection = db["messages"]
chats_collection = db["chats"]