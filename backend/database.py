from motor.motor_asyncio import AsyncIOMotorClient
import os

client = AsyncIOMotorClient(os.getenv("MONGODB_URI"))
db = client["chatbot_db"]
messages_collection = db["messages"]
chats_collection = db["chats"]