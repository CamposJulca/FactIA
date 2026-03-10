import pandas as pd
import json
from pathlib import Path

# cargar metadata
df = pd.read_csv("metadata_facturas_2026.csv")

duplicados = df[df.duplicated(subset=["nit", "numero_factura"], keep=False)]
duplicados = duplicados.sort_values(["nit", "numero_factura"])

# cargar correos
with open("procesados.json", "r", encoding="utf-8") as f:
    correos = json.load(f)

# indexar zips
zip_index = {}

for mail_id, data in correos.items():

    for att in data.get("attachments", []):

        zip_name = att["filename"]

        zip_index[zip_name] = {
            "mail_id": mail_id,
            "subject": data["subject"],
            "from": data["from"],
            "received": data["receivedDateTime"],
            "storage_path": att["storage_path"]
        }

# ejemplo factura
ejemplo = duplicados[
    (duplicados["nit"] == 830042244)
    & (duplicados["numero_factura"] == "BOGO19018")
]

for ruta in ejemplo["archivo"]:

    carpeta = Path(ruta).parent.name

    print("\n==============================")
    print("XML:", ruta)
    print("CARPETA:", carpeta)

    for zip_name, info in zip_index.items():

        if carpeta in zip_name:

            print("\nZIP:", zip_name)
            print("FROM:", info["from"])
            print("SUBJECT:", info["subject"])
            print("FECHA:", info["received"])
            print("PATH:", info["storage_path"])