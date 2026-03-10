'''
import os
import zipfile
from pathlib import Path
from .validator import is_factura_electronica
from .config import RAW_FOLDER, CURATED_FOLDER, REJECTED_FOLDER


class ZipClassifier:

    def __init__(self):
        self.total = 0
        self.facturas = 0
        self.no_facturas = 0
        self.sin_xml = 0
        self.errores = 0

    def process_all(self):

        for root, _, files in os.walk(RAW_FOLDER):

            for file in files:

                if file.lower().endswith(".zip"):
                    self.total += 1
                    zip_path = Path(root) / file
                    self._process_zip(zip_path)

        self._print_summary()

    def _process_zip(self, zip_path: Path):

        try:
            with zipfile.ZipFile(zip_path, "r") as z:

                tiene_xml = False
                es_factura = False

                for name in z.namelist():

                    if name.lower().endswith(".xml"):
                        tiene_xml = True

                        with z.open(name) as xml_file:
                            contenido = xml_file.read().decode("utf-8", errors="ignore")

                            if is_factura_electronica(contenido):
                                es_factura = True
                                break

                relative_path = zip_path.relative_to(RAW_FOLDER).with_suffix("")

                if not tiene_xml:
                    destino = REJECTED_FOLDER / "sin_xml" / relative_path
                    self.sin_xml += 1
                elif not es_factura:
                    destino = REJECTED_FOLDER / "no_facturas" / relative_path
                    self.no_facturas += 1
                else:
                    destino = CURATED_FOLDER / relative_path
                    self.facturas += 1

                os.makedirs(destino, exist_ok=True)
                z.extractall(destino)

        except Exception:
            self.errores += 1

    def _print_summary(self):

        print("\n===== RESULTADO TRANSFORMACION =====")
        print(f"Total ZIP: {self.total}")
        print(f"Facturas válidas: {self.facturas}")
        print(f"No facturas: {self.no_facturas}")
        print(f"Sin XML: {self.sin_xml}")
        print(f"Errores: {self.errores}")
        print("====================================\n")
'''

# transformacion_service/classifier.py

import os
import zipfile
from pathlib import Path
from .validator import DocumentValidator
from .config import RAW_FOLDER, CURATED_FOLDER, REJECTED_FOLDER


class ZipClassifier:

    def __init__(self):
        self.validator = DocumentValidator()

        self.total = 0
        self.stats = {
            "Invoice": 0,
            "CreditNote": 0,
            "DebitNote": 0,
            "ApplicationResponse": 0,
            "AttachedDocument": 0,
            "Unknown": 0,
            "InvalidXML": 0,
            "SinXML": 0
        }

    # ==========================================================
    # PROCESAR TODOS LOS ZIP
    # ==========================================================
    def process_all(self):

        for root, _, files in os.walk(RAW_FOLDER):

            for file in files:

                if file.lower().endswith(".zip"):
                    self.total += 1
                    zip_path = Path(root) / file
                    self._process_zip(zip_path)

        self._print_summary()

    # ==========================================================
    # PROCESAR ZIP INDIVIDUAL
    # ==========================================================
    def _process_zip(self, zip_path: Path):

        try:
            with zipfile.ZipFile(zip_path, "r") as z:

                xml_files = [f for f in z.namelist() if f.lower().endswith(".xml")]

                if not xml_files:
                    self.stats["SinXML"] += 1
                    self._move_zip(zip_path, "SinXML")
                    return

                detected_types = []

                # Analizar todos los XML
                for xml_name in xml_files:

                    with z.open(xml_name) as xml_file:

                        contenido = xml_file.read().decode("utf-8", errors="ignore")

                        doc_type = self.validator.detect_document_type(contenido)

                        detected_types.append(doc_type)

                # ==================================================
                # PRIORIDAD DOCUMENTAL
                # ==================================================

                if "Invoice" in detected_types:
                    final_type = "Invoice"

                elif "CreditNote" in detected_types:
                    final_type = "CreditNote"

                elif "DebitNote" in detected_types:
                    final_type = "DebitNote"

                elif "ApplicationResponse" in detected_types:
                    final_type = "ApplicationResponse"

                elif "AttachedDocument" in detected_types:
                    final_type = "AttachedDocument"

                else:
                    final_type = "Unknown"

                self.stats[final_type] += 1
                self._move_zip(zip_path, final_type)

        except Exception:
            self.stats["InvalidXML"] += 1
            self._move_zip(zip_path, "InvalidXML")

    # ==========================================================
    # MOVER Y EXTRAER ZIP SEGÚN TIPO
    # ==========================================================
    def _move_zip(self, zip_path: Path, document_type: str):

        relative_path = zip_path.relative_to(RAW_FOLDER).with_suffix("")

        if document_type == "Invoice":
            destino = CURATED_FOLDER / "facturas" / relative_path
        else:
            destino = REJECTED_FOLDER / document_type / relative_path

        os.makedirs(destino, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(destino)

    # ==========================================================
    # RESUMEN FINAL
    # ==========================================================
    def _print_summary(self):

        print("\n===== RESULTADO CLASIFICACIÓN =====")
        print(f"Total ZIP procesados: {self.total}")

        for k, v in self.stats.items():
            print(f"{k}: {v}")

        print("====================================\n")