import os
from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

MAILBOX = "facturacion@finagro.com.co"
START_DATE = "2026-01-01T00:00:00Z"

VERIFY_SSL = True                                                                                                                                                              