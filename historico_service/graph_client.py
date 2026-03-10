import requests
import certifi
from .config import MAILBOX, START_DATE

class GraphClient:

    def __init__(self, access_token):
        self.headers = {"Authorization": f"Bearer {access_token}"}
        self.verify_ssl = certifi.where()

    def get_messages(self, next_link=None):

        if next_link:
            url = next_link
        else:
            url = (
                f"https://graph.microsoft.com/v1.0/users/{MAILBOX}/messages"
                f"?$filter=receivedDateTime ge {START_DATE}"
                f"&$orderby=receivedDateTime asc"
                f"&$top=50"
            )

        return requests.get(url, headers=self.headers, verify=self.verify_ssl)

    def get_attachments(self, message_id):

        url = (
            f"https://graph.microsoft.com/v1.0/users/{MAILBOX}"
            f"/messages/{message_id}/attachments"
        )

        return requests.get(url, headers=self.headers, verify=self.verify_ssl)