from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient("mongodb://localhost:27017")

db = client["chatbot_db"]

messages_collection = db["messages"]
chats_collection = db["chats"]