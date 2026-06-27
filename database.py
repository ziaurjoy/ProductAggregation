from motor.motor_asyncio import AsyncIOMotorClient
from config import settings

class DatabaseHelper:
    def __init__(self):
        self.client: AsyncIOMotorClient = None
        self.db = None

    def connect(self):
        self.client = AsyncIOMotorClient(settings.mongodb_url)
        self.db = self.client[settings.database_name]

    def disconnect(self):
        if self.client:
            self.client.close()

db_helper = DatabaseHelper()

def get_db():
    return db_helper.db
