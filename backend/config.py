import os

REPOSITORY_DIR = os.getenv("REPOSITORY_DIR", "/repository")
DB_PATH = os.getenv("DB_PATH", "/app/data/picasso.db")
WEB_PORT = int(os.getenv("WEB_PORT", "80"))
CAR_DATALOG_SUBDIR = "Car_datalog"
