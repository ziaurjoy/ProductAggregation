from motor.motor_asyncio import AsyncIOMotorClient
from config import settings

class DatabaseHelper:
    def __init__(self):
        self.client: AsyncIOMotorClient = None
        self.db = None

    def connect(self):
        import os
        mongodb_url = os.getenv("MONGODB_URL", settings.mongodb_url)

        self.client = AsyncIOMotorClient(mongodb_url)
        self.db = self.client.get_default_database()

    def disconnect(self):
        if self.client:
            self.client.close()

db_helper = DatabaseHelper()

def get_db():
    return db_helper.db
