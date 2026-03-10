'''
# transformacion_service/metadata_extractor.py

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
import re
from decimal import Decimal
from .metadata_writer import MetadataWriter


class InvoiceMetadataExtractor:

    def __init__(self, root_path: str):
        self.root_path = Path(root_path)

        self.namespaces = {
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        }

        self.results = []

    # ==========================================================
    # PROCESO GENERAL
    # ==========================================================
    def process_all(self):

        logging.info("===== INICIANDO EXTRACCIÓN DE METADATA =====")

        for xml_path in self.root_path.rglob("*.xml"):
            self._process_file(xml_path)

        self._save_results()

        logging.info(f"Total facturas procesadas: {len(self.results)}")
        logging.info("===== FIN EXTRACCIÓN =====")

    # ==========================================================
    # PROCESAMIENTO POR ARCHIVO
    # ==========================================================
    def _process_file(self, xml_path: Path):

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()

            invoice_root = self._resolve_invoice_root(root)

            if invoice_root is None:
                return

            metadata = self._build_metadata(invoice_root)

            if metadata:
                metadata["ruta_xml"] = str(xml_path)
                self.results.append(metadata)

            logging.info(
                f"OK → NIT: {metadata['nit_proveedor']} | "
                f"Factura: {metadata['numero_factura']} | "
                f"Valor: {metadata['valor_total']} | "
                f"Archivo: {xml_path}"
            )

        except Exception as e:
            logging.error(f"Error procesando {xml_path}: {e}")

    # ==========================================================
    # RESOLVER TIPO DOCUMENTO
    # ==========================================================
    def _resolve_invoice_root(self, root):

        root_tag = self._strip_namespace(root.tag)

        if root_tag == "Invoice":
            return root

        if root_tag == "AttachedDocument":
            return self._extract_invoice_from_cdata(root)

        return None

    # ==========================================================
    # EXTRAER FACTURA DESDE CDATA
    # ==========================================================
    def _extract_invoice_from_cdata(self, root):

        for elem in root.iter():
            if elem.text and "<Invoice" in elem.text:
                try:
                    return ET.fromstring(elem.text.strip())
                except Exception:
                    return None

        return None

    # ==========================================================
    # CONSTRUIR METADATA (ORQUESTADOR)
    # ==========================================================
    def _build_metadata(self, root):

        nit = self._extract_supplier_nit(root)
        numero = self._extract_invoice_number(root)
        valor = self._extract_total_amount(root)

        if nit and numero and valor:
            return {
                "nit_proveedor": nit,
                "numero_factura": numero,
                "valor_total": valor
            }

        return None

    # ==========================================================
    # METADATO 1: NÚMERO FACTURA
    # ==========================================================
    def _extract_invoice_number(self, root):

        for elem in root.findall(".//cbc:ID", self.namespaces):
            if elem.text and elem.text.strip():
                numero_raw = elem.text.strip()

                # limpiar caracteres no numéricos
                numero_limpio = re.sub(r"\D", "", numero_raw)

                if numero_limpio:
                    return numero_limpio

        return None

    # ==========================================================
    # METADATO 2: NIT PROVEEDOR
    # ==========================================================
    def _extract_supplier_nit(self, root):

        for elem in root.findall(
            ".//cac:AccountingSupplierParty//cbc:CompanyID",
            self.namespaces
        ):
            if elem.text and elem.text.strip():
                return elem.text.strip()

        return None

    # ==========================================================
    # METADATO 3: VALOR TOTAL FACTURA
    # ==========================================================
    def _extract_total_amount(self, root):

        payable = root.find(
            ".//cac:LegalMonetaryTotal/cbc:PayableAmount",
            self.namespaces
        )

        if payable is not None and payable.text:
            try:
                return str(Decimal(payable.text.strip()))
            except Exception:
                return None

        return None

    # ==========================================================
    # UTILIDADES
    # ==========================================================
    def _strip_namespace(self, tag: str):
        return tag.split("}")[-1]

    # ==========================================================
    # GUARDAR RESULTADOS
    # ==========================================================
    def _save_results(self):

        output_file = "facturas_metadata.json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=4, ensure_ascii=False)

        logging.info(f"Archivo generado: {output_file}")
'''

'''
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from decimal import Decimal
import re

from .metadata_writer import MetadataWriter


class InvoiceMetadataExtractor:

    def __init__(self, root_path):

        self.root_path = Path(root_path)

        self.namespaces = {
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        }

        self.writer = MetadataWriter()

        self.total = 0
        self.errores = 0

        self.results = []

    # ==========================================================
    # PROCESO GENERAL
    # ==========================================================
    def process_all(self):

        logging.info("===== INICIANDO EXTRACCIÓN DE METADATA =====")

        if not self.root_path.exists():
            logging.error(f"Ruta no encontrada: {self.root_path}")
            return

        for xml_path in self.root_path.rglob("*.xml"):

            self._process_file(xml_path)

        self._save_results()

        logging.info("===== RESUMEN =====")
        logging.info(f"Facturas procesadas: {self.total}")
        logging.info(f"Errores: {self.errores}")

    # ==========================================================
    # PROCESAMIENTO POR ARCHIVO
    # ==========================================================
    def _process_file(self, xml_path):

        try:

            tree = ET.parse(xml_path)
            root = tree.getroot()

            invoice_root = self._resolve_invoice_root(root)

            # no es factura
            if invoice_root is None:
                return

            nit = self._extract_supplier_nit(invoice_root)
            numero = self._extract_invoice_number(invoice_root)
            valor = self._extract_total_amount(invoice_root)

            if not nit or not numero or not valor:
                logging.warning(f"Metadata incompleta en {xml_path}")
                return

            self.total += 1

            logging.info(
                f"OK → NIT: {nit} | Factura: {numero} | Valor: {valor} | Archivo: {xml_path}"
            )

            metadata = {
                "nit": nit,
                "numero_factura": numero,
                "valor": valor,
                "archivo": str(xml_path)
            }

            self.results.append(metadata)

            # persistencia CSV
            self.writer.write(
                nit,
                numero,
                valor,
                str(xml_path)
            )

        except Exception as e:

            self.errores += 1
            logging.error(f"ERROR procesando {xml_path}: {e}")

    # ==========================================================
    # RESOLVER TIPO DOCUMENTO
    # ==========================================================
    def _resolve_invoice_root(self, root):

        root_tag = self._strip_namespace(root.tag)

        # factura directa
        if root_tag == "Invoice":
            return root

        # factura embebida en AttachedDocument
        if root_tag == "AttachedDocument":
            return self._extract_invoice_from_cdata(root)

        return None

    # ==========================================================
    # EXTRAER FACTURA DESDE CDATA
    # ==========================================================
    def _extract_invoice_from_cdata(self, root):

        for elem in root.iter():

            if elem.text and "<Invoice" in elem.text:

                try:
                    return ET.fromstring(elem.text.strip())
                except Exception:
                    return None

        return None

    # ==========================================================
    # METADATO 1: NÚMERO FACTURA
    # ==========================================================
    def _extract_invoice_number(self, root):

        elem = root.find("cbc:ID", self.namespaces)

        if elem is not None and elem.text:

            numero_raw = elem.text.strip()

            # eliminar todo lo que no sea número
            numero_limpio = re.sub(r"\D", "", numero_raw)

            if numero_limpio:
                return numero_limpio

        return None

    # ==========================================================
    # METADATO 2: NIT PROVEEDOR
    # ==========================================================
    def _extract_supplier_nit(self, root):

        elem = root.find(
            ".//cac:AccountingSupplierParty//cbc:CompanyID",
            self.namespaces
        )

        if elem is not None and elem.text:

            return elem.text.strip()

        return None

    # ==========================================================
    # METADATO 3: VALOR TOTAL FACTURA
    # ==========================================================
    def _extract_total_amount(self, root):

        payable = root.find(
            ".//cac:LegalMonetaryTotal/cbc:PayableAmount",
            self.namespaces
        )

        if payable is not None and payable.text:

            try:
                return str(Decimal(payable.text.strip()))
            except Exception:
                return None

        return None

    # ==========================================================
    # UTILIDADES
    # ==========================================================
    def _strip_namespace(self, tag):

        return tag.split("}")[-1]

    # ==========================================================
    # GUARDAR JSON
    # ==========================================================
    def _save_results(self):

        output_file = "facturas_metadata.json"

        with open(output_file, "w", encoding="utf-8") as f:

            json.dump(self.results, f, indent=4, ensure_ascii=False)

        logging.info(f"Archivo JSON generado: {output_file}")
'''

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from decimal import Decimal
import re
import calendar
from datetime import datetime

from .metadata_writer import MetadataWriter


class InvoiceMetadataExtractor:

    def __init__(self, root_path):

        self.root_path = Path(root_path)

        self.namespaces = {
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        }

        self.writer = MetadataWriter()

        self.total = 0
        self.errores = 0
        self.results = []

        # cargar metadata del histórico de correos
        self.fechas_recepcion = self._load_procesados()

    # ==========================================================
    # CARGAR PROCESADOS.JSON
    # ==========================================================
    def _load_procesados(self):

        try:

            with open("procesados.json", "r", encoding="utf-8") as f:
                data = json.load(f)

            fechas = {}

            for message_id, info in data.items():

                fecha = info.get("receivedDateTime")

                for att in info.get("attachments", []):

                    filename = att.get("filename")

                    if filename:
                        fechas[filename] = fecha

            logging.info(f"Correos indexados: {len(fechas)}")

            return fechas

        except Exception as e:

            logging.warning(f"No se pudo cargar procesados.json: {e}")
            return {}
    
    # ==========================================================
    # PROCESO GENERAL
    # ==========================================================
    def process_all(self):

        logging.info("===== INICIANDO EXTRACCIÓN DE METADATA =====")

        if not self.root_path.exists():
            logging.error(f"Ruta no encontrada: {self.root_path}")
            return

        for xml_path in self.root_path.rglob("*.xml"):

            self._process_file(xml_path)

        self._save_results()

        logging.info("===== RESUMEN =====")
        logging.info(f"Facturas procesadas: {self.total}")
        logging.info(f"Errores: {self.errores}")

    # ==========================================================
    # PROCESAMIENTO POR ARCHIVO
    # ==========================================================
    def _process_file(self, xml_path):

        try:

            tree = ET.parse(xml_path)
            root = tree.getroot()

            invoice_root = self._resolve_invoice_root(root)

            if invoice_root is None:
                return

            proveedor_nit = self._extract_supplier_nit(invoice_root)

            numero_original = self._extract_invoice_number_original(invoice_root)

            numero_factura = re.sub(r"\D", "", numero_original)

            codigo = self._extract_codigo(numero_original)

            iva = self._extract_iva(invoice_root)

            fecha_emision = self._extract_fecha_emision(xml_path)

            fecha_vencimiento = self._last_day_month(fecha_emision)

            observaciones = f"Factura {numero_factura} radicado ***"

            valor_factura = self._extract_valor_factura(invoice_root)

            if not proveedor_nit or not numero_factura:

                logging.warning(f"Metadata incompleta en {xml_path}")
                return

            self.total += 1

            metadata = {
                "proveedor_nit": proveedor_nit,
                "fecha_emision": fecha_emision,
                "fecha_vencimiento": fecha_vencimiento,
                "codigo": codigo,
                "numero_factura": numero_factura,
                "valor_factura": valor_factura,
                "observaciones": observaciones,
                "iva_facturado_proveedor": iva,
                "archivo": str(xml_path)
            }

            logging.info(
                f"OK → NIT:{proveedor_nit} | Factura:{numero_factura} | IVA:{iva}"
            )

            self.results.append(metadata)

            # escritura CSV
            self.writer.write(
                proveedor_nit,
                numero_factura,
                iva,
                str(xml_path)
            )

        except Exception as e:

            self.errores += 1
            logging.error(f"ERROR procesando {xml_path}: {e}")

    # ==========================================================
    # RESOLVER DOCUMENTO
    # ==========================================================
    def _resolve_invoice_root(self, root):

        root_tag = self._strip_namespace(root.tag)

        if root_tag == "Invoice":
            return root

        if root_tag == "AttachedDocument":
            return self._extract_invoice_from_cdata(root)

        return None

    # ==========================================================
    # EXTRAER FACTURA DESDE ATTACHEDDOCUMENT
    # ==========================================================
    def _extract_invoice_from_cdata(self, root):

        for elem in root.iter():

            if elem.text and "<Invoice" in elem.text:

                try:
                    return ET.fromstring(elem.text.strip())
                except Exception:
                    return None

        return None

    # ==========================================================
    # NUMERO FACTURA ORIGINAL
    # ==========================================================
    def _extract_invoice_number_original(self, root):

        elem = root.find("cbc:ID", self.namespaces)

        if elem is not None and elem.text:
            return elem.text.strip()

        return ""

    # ==========================================================
    # CODIGO FACTURA
    # ==========================================================
    def _extract_codigo(self, numero_original):

        codigo = re.sub(r"\d", "", numero_original)

        if codigo:
            return codigo

        return "FACT"

    # ==========================================================
    # NIT PROVEEDOR
    # ==========================================================
    def _extract_supplier_nit(self, root):

        elem = root.find(
            ".//cac:AccountingSupplierParty//cbc:CompanyID",
            self.namespaces
        )

        if elem is not None and elem.text:
            return elem.text.strip()

        return None

    # ==========================================================
    # IVA FACTURADO
    # ==========================================================
    def _extract_iva(self, root):

        total = Decimal("0")

        for tax in root.findall(
            ".//cac:TaxTotal/cbc:TaxAmount",
            self.namespaces
        ):

            if tax.text:

                try:
                    total += Decimal(tax.text)
                except Exception:
                    pass

        return str(total)

    # ==========================================================
    # FECHA EMISION (desde procesados.json)
    # ==========================================================
    def _extract_fecha_emision(self, xml_path):

        carpeta = xml_path.parent.name
        zip_name = f"{carpeta}.zip"

        fecha = self.fechas_recepcion.get(zip_name)

        if fecha:
            return fecha.split("T")[0]

        return None
    
    # ==========================================================
    # VALOR DE LA FACTURA
    # ==========================================================
    def _extract_valor_factura(self, root):

        payable = root.find(
            ".//cac:LegalMonetaryTotal/cbc:PayableAmount",
            self.namespaces
        )

        if payable is not None and payable.text:

            try:
                return str(Decimal(payable.text.strip()))
            except Exception:
                return None

        return None

    # ==========================================================
    # CALCULAR ULTIMO DIA DEL MES
    # ==========================================================
    def _last_day_month(self, fecha):

        if not fecha:
            return None

        dt = datetime.strptime(fecha, "%Y-%m-%d")

        last_day = calendar.monthrange(dt.year, dt.month)[1]

        return f"{dt.year}-{dt.month:02d}-{last_day}"

    # ==========================================================
    # UTILIDAD
    # ==========================================================
    def _strip_namespace(self, tag):

        return tag.split("}")[-1]

    # ==========================================================
    # GUARDAR JSON
    # ==========================================================
    def _save_results(self):

        output_file = "facturas_metadata.json"

        with open(output_file, "w", encoding="utf-8") as f:

            json.dump(self.results, f, indent=4, ensure_ascii=False)

        logging.info(f"Archivo JSON generado: {output_file}")