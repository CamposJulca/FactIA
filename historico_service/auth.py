import requests
import certifi
from .config import TENANT_ID, CLIENT_ID, CLIENT_SECRET

def get_access_token():

    token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    }

    response = requests.post(token_url, data=data, verify=certifi.where())

    if response.status_code != 200:
        raise Exception("Error obteniendo token")

    return response.json()["access_token"]