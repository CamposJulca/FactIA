import csv
from pathlib import Path


class MetadataWriter:

    def __init__(self, output_file="metadata_facturas_2026.csv"):

        self.output_file = Path(output_file)

        # Crear archivo si no existe
        if not self.output_file.exists():

            with open(self.output_file, "w", newline="", encoding="utf-8") as f:

                writer = csv.writer(f)

                writer.writerow([
                    "nit",
                    "numero_factura",
                    "valor",
                    "archivo"
                ])

    def write(self, nit, factura, valor, archivo):

        with open(self.output_file, "a", newline="", encoding="utf-8") as f:

            writer = csv.writer(f)

            writer.writerow([
                nit,
                factura,
                valor,
                archivo
            ])