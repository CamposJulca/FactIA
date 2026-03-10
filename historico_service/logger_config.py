import logging
import sys
from datetime import datetime

def setup_logger():

    log_name = f"historico_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_name, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    return logging