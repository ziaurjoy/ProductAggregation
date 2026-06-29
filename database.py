from motor.motor_asyncio import AsyncIOMotorClient
from config import settings

class DatabaseHelper:
    def __init__(self):
        self.client: AsyncIOMotorClient = None
        self.db = None

    def connect(self):
        import os
        mongodb_url = os.getenv("MONGODB_URL", settings.mongodb_url)
        database_name = os.getenv("DATABASE_NAME", settings.database_name)
        if database_name and (database_name.startswith("mongodb://") or database_name.startswith("mongodb+srv://")):
            mongodb_url = database_name
            database_name = "aggregation_product_db"
        self.client = AsyncIOMotorClient(mongodb_url)
        self.db = self.client[database_name]

    def disconnect(self):
        if self.client:
            self.client.close()

db_helper = DatabaseHelper()

def get_db():
    return db_helper.db
