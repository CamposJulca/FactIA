from .logger_config import setup_logger
from .auth import get_access_token
from .graph_client import GraphClient
from .downloader import Downloader

def main():

    logger = setup_logger()

    logger.info("Iniciando servicio histórico modular")

    token = get_access_token()

    graph = GraphClient(token)

    downloader = Downloader(graph, logger)

    downloader.run()

    logger.info("Proceso terminado correctamente")

if __name__ == "__main__":
    main()