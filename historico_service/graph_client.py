import time
import threading
import concurrent.futures
import requests
import certifi
from .config import MAILBOX, START_DATE

TIMEOUT_API      = (10, 30)    # connect, read — para endpoints JSON
TIMEOUT_STREAM   = (10, 30)    # por cada chunk de streaming
DOWNLOAD_TIMEOUT = 90          # segundos máximos para descargar un archivo completo
PAGE_SIZE        = 10
SELECT_MSG       = "id,subject,receivedDateTime,from,hasAttachments"
SELECT_ATT       = "id,name,contentType,size"


class GraphClient:

    def __init__(self, access_token, fecha_desde=None, fecha_hasta=None, refresh_token_fn=None):
        self.headers          = {"Authorization": f"Bearer {access_token}"}
        self.verify_ssl       = certifi.where()
        self.fecha_desde      = fecha_desde or START_DATE
        self.fecha_hasta      = fecha_hasta
        self.refresh_token_fn = refresh_token_fn   # callable → nuevo token

    def _refresh(self):
        """Renueva el token si tenemos la función de refresh."""
        if self.refresh_token_fn:
            new_token = self.refresh_token_fn()
            self.headers["Authorization"] = f"Bearer {new_token}"
            return True
        return False

    def _request(self, method, url, intento=1, max_intentos=3,
                 stream=False, timeout=None):
        timeout = timeout or TIMEOUT_API
        try:
            resp = requests.request(
                method, url,
                headers=self.headers,
                verify=self.verify_ssl,
                timeout=timeout,
                stream=stream,
            )

            # Token expirado — refrescar y reintentar una vez
            if resp.status_code == 401 and intento == 1:
                if self._refresh():
                    return self._request(method, url, intento=2,
                                         max_intentos=max_intentos,
                                         stream=stream, timeout=timeout)

            # Rate limit — respetar Retry-After
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 2 ** intento))
                time.sleep(wait)
                if intento < max_intentos:
                    return self._request(method, url, intento + 1,
                                         max_intentos, stream, timeout)

            # Errores de servidor — backoff exponencial
            if resp.status_code in (500, 502, 503, 504) and intento < max_intentos:
                time.sleep(2 ** intento)
                return self._request(method, url, intento + 1,
                                     max_intentos, stream, timeout)

            return resp

        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as exc:
            if intento < max_intentos:
                time.sleep(2 ** intento)
                return self._request(method, url, intento + 1,
                                     max_intentos, stream, timeout)
            raise exc

    # ── Endpoints ─────────────────────────────────────────────────────────────

    def get_messages(self, next_link=None):
        if next_link:
            url = next_link
        else:
            filtro = f"receivedDateTime ge {self.fecha_desde}"
            if self.fecha_hasta:
                filtro += f" and receivedDateTime le {self.fecha_hasta}"
            url = (
                f"https://graph.microsoft.com/v1.0/users/{MAILBOX}/messages"
                f"?$filter={filtro}"
                f"&$orderby=receivedDateTime asc"
                f"&$top={PAGE_SIZE}"
                f"&$select={SELECT_MSG}"
            )
        return self._request("GET", url)

    def get_attachments_metadata(self, message_id):
        """Solo id, name, size — sin contentBytes."""
        url = (
            f"https://graph.microsoft.com/v1.0/users/{MAILBOX}"
            f"/messages/{message_id}/attachments"
            f"?$select={SELECT_ATT}"
        )
        return self._request("GET", url)

    def download_attachment(self, message_id, attachment_id, dest_path):
        """
        Descarga binario en streaming con timeout total duro (DOWNLOAD_TIMEOUT s).
        Si se estanca mid-stream, lanza TimeoutError y el downloader lo registra
        como error y continúa con el siguiente mensaje.
        """
        url = (
            f"https://graph.microsoft.com/v1.0/users/{MAILBOX}"
            f"/messages/{message_id}/attachments/{attachment_id}/$value"
        )

        exc_box = [None]

        def _do():
            try:
                resp = self._request("GET", url, stream=True,
                                     timeout=TIMEOUT_STREAM)
                resp.raise_for_status()
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
            except Exception as e:
                exc_box[0] = e

        t = threading.Thread(target=_do, daemon=True)
        t.start()
        t.join(timeout=DOWNLOAD_TIMEOUT)

        if t.is_alive():
            raise TimeoutError(
                f"Timeout ({DOWNLOAD_TIMEOUT}s) descargando adjunto — se omite"
            )
        if exc_box[0]:
            raise exc_box[0]
