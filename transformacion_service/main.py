'''
# Etapa 1: Clasificación de documentos

from .classifier import ZipClassifier


def main():

    classifier = ZipClassifier()
    classifier.process_all()


if __name__ == "__main__":
    main()
'''

import logging
from .metadata_extractor import InvoiceMetadataExtractor


BASE_FOLDER = "curado_2026/facturas"


def setup_logger():

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    return logging.getLogger("transformacion_service")


def main():

    logger = setup_logger()

    logger.info("===== INICIANDO EXTRACCIÓN DE METADATA =====")

    extractor = InvoiceMetadataExtractor(BASE_FOLDER)

    extractor.process_all()

    logger.info("===== PROCESO FINALIZADO =====")


if __name__ == "__main__":
    main()
