import os
import time
from .control import load_processed, save_processed
from .storage import build_path
from .extractor import extraer_zip

# Pausa entre páginas para no saturar la API
DELAY_ENTRE_PAGINAS = 0.5   # segundos


class Downloader:

    def __init__(self, graph_client, logger, abort_event=None):
        self.graph        = graph_client
        self.logger       = logger
        self.processed    = load_processed()
        self.abort_event  = abort_event
        # Carpeta donde se extraen los ZIPs (env var o default junto a DATA_DIR)
        data_dir = os.getenv('FACTIA_DATA_DIR', '/data/factia')
        self.extraidos_dir = os.path.join(data_dir, 'extraidos')

    def run(self):

        next_link   = None
        total_new   = 0
        total_skip  = 0
        total_error = 0
        pagina      = 0

        while True:

            if self.abort_event and self.abort_event.is_set():
                self.logger.warning(
                    f"Descarga abortada. Nuevos: {total_new} | Omitidos: {total_skip} | Errores: {total_error}"
                )
                save_processed(self.processed)
                return

            # ── Obtener página de mensajes ────────────────────────────────
            pagina += 1
            try:
                response = self.graph.get_messages(next_link)
            except Exception as exc:
                self.logger.error(f"Error obteniendo página {pagina}: {exc}")
                save_processed(self.processed)
                break

            if response.status_code != 200:
                self.logger.error(f"HTTP {response.status_code} en página {pagina}")
                save_processed(self.processed)
                break

            data     = response.json()
            mensajes = data.get("value", [])
            self.logger.info(f"Página {pagina}: {len(mensajes)} mensajes recibidos")

            # ── Procesar cada mensaje ─────────────────────────────────────
            for message in mensajes:

                if self.abort_event and self.abort_event.is_set():
                    self.logger.warning("Abort detectado — guardando progreso...")
                    save_processed(self.processed)
                    return

                message_id = message["id"]
                subject    = message.get("subject", "")

                # Ya descargado — omitir
                if message_id in self.processed:
                    total_skip += 1
                    self.logger.info(f"[OMITIDO] Ya descargado: {subject}")
                    continue

                # Nuevo mensaje — intentar procesar
                try:
                    received = message["receivedDateTime"]
                    sender   = message.get("from", {}).get("emailAddress", {}).get("address")

                    self.logger.info(f"Procesando: {subject}")

                    attachments_data = []

                    att_response = self.graph.get_attachments_metadata(message_id)

                    if att_response.status_code != 200:
                        self.logger.warning(f"No se pudieron obtener adjuntos (HTTP {att_response.status_code}): {subject}")
                    else:
                        for att in att_response.json().get("value", []):
                            filename = att.get("name", "")
                            if not filename.lower().endswith(".zip"):
                                continue

                            size_kb   = round(att.get("size", 0) / 1024)
                            path      = build_path(received)
                            file_path = f"{path}/{filename}"

                            self.logger.info(f"Descargando: {filename} ({size_kb} KB)...")
                            self.graph.download_attachment(
                                message_id, att["id"], file_path
                            )
                            self.logger.info(f"Descargado: {filename} ({size_kb} KB)")

                            # Extraer ZIP a carpeta local
                            dest = extraer_zip(file_path, self.extraidos_dir)
                            if dest:
                                self.logger.info(f"Extraído en: {dest}")

                            attachments_data.append({
                                "filename":     filename,
                                "storage_path": path,
                            })

                    # Marcar mensaje como procesado y guardar progreso
                    self.processed[message_id] = {
                        "receivedDateTime": received,
                        "subject":          subject,
                        "from":             sender,
                        "hasAttachments":   message.get("hasAttachments", False),
                        "attachments":      attachments_data,
                    }
                    total_new += 1
                    save_processed(self.processed)

                except Exception as exc:
                    total_error += 1
                    self.logger.error(f"Error procesando mensaje '{subject}': {exc} — se continúa")
                    # No se marca como procesado: se reintentará en la próxima ejecución

            # ── Siguiente página o fin ────────────────────────────────────
            next_link = data.get("@odata.nextLink")

            if not next_link:
                break

            # Pausa breve entre páginas para no saturar Graph API
            time.sleep(DELAY_ENTRE_PAGINAS)

        self.logger.info(
            f"Descarga finalizada. Nuevos: {total_new} | Omitidos: {total_skip} | Errores: {total_error}"
        )
