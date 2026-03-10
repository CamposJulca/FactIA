import os
from datetime import datetime

BASE_FOLDER = "historico_2026"

def build_path(received_datetime):

    dt = datetime.fromisoformat(received_datetime.replace("Z", "+00:00"))

    year = dt.year
    month = dt.strftime("%m_%B").lower()
    week = dt.isocalendar()[1]

    path = os.path.join(BASE_FOLDER, str(year), month, f"semana_{week:02d}")

    os.makedirs(path, exist_ok=True)

    return path