from .logger_config import setup_logger
from .auth import get_access_token
from .graph_client import GraphClient
from .downloader import Downloader

def main(fecha_desde=None, fecha_hasta=None, abort_event=None):

    logger = setup_logger()

    logger.info("Iniciando servicio histórico modular")

    token = get_access_token()

    graph = GraphClient(
        token,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        refresh_token_fn=get_access_token,   # renueva automáticamente si el token expira
    )

    downloader = Downloader(graph, logger, abort_event=abort_event)

    downloader.run()

    logger.info("Proceso terminado correctamente")

if __name__ == "__main__":
    main()