import base64
from .control import load_processed, save_processed
from .storage import build_path


class Downloader:

    def __init__(self, graph_client, logger):
        self.graph = graph_client
        self.logger = logger
        self.processed = load_processed()

    def run(self):

        next_link = None

        while True:

            response = self.graph.get_messages(next_link)

            if response.status_code != 200:
                self.logger.error("Error consultando mensajes")
                break

            data = response.json()

            for message in data.get("value", []):

                message_id = message["id"]

                if message_id in self.processed:
                    continue

                received = message["receivedDateTime"]
                subject = message.get("subject", "")
                sender = message.get("from", {}).get("emailAddress", {}).get("address")

                self.logger.info(f"Procesando mensaje: {subject}")

                att_response = self.graph.get_attachments(message_id)
                attachments_data = []

                for att in att_response.json().get("value", []):

                    filename = att.get("name")

                    if filename and filename.lower().endswith(".zip"):

                        path = build_path(received)
                        file_path = f"{path}/{filename}"

                        with open(file_path, "wb") as f:
                            f.write(base64.b64decode(att["contentBytes"]))

                        self.logger.info(f"Descargado: {filename}")

                        attachments_data.append({
                            "filename": filename,
                            "storage_path": path
                        })

                # Guardamos metadata completa del mensaje
                self.processed[message_id] = {
                    "receivedDateTime": received,
                    "subject": subject,
                    "from": sender,
                    "hasAttachments": message.get("hasAttachments", False),
                    "attachments": attachments_data
                }

            next_link = data.get("@odata.nextLink")

            if not next_link:
                break

        save_processed(self.processed)
        self.logger.info("Descarga finalizada correctamente")