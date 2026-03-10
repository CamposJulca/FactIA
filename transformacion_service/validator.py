'''
def is_factura_electronica(xml_content: str) -> bool:
    return (
        "<Invoice" in xml_content and
        "Factura Electr" in xml_content
    )
'''

# transformacion_service/validator.py

import xml.etree.ElementTree as ET


class DocumentValidator:

    def __init__(self):
        pass

    # ==========================================================
    # MÉTODO PRINCIPAL
    # ==========================================================
    def detect_document_type(self, xml_content: str) -> str:
        """
        Retorna el tipo real de documento UBL.
        """

        try:
            root = ET.fromstring(xml_content)
            root_tag = self._strip_namespace(root.tag)

            # Caso 1: Invoice directa
            if root_tag == "Invoice":
                return "Invoice"

            # Caso 2: CreditNote directa
            if root_tag == "CreditNote":
                return "CreditNote"

            # Caso 3: DebitNote directa
            if root_tag == "DebitNote":
                return "DebitNote"

            # Caso 4: AttachedDocument (puede contener Invoice dentro)
            if root_tag == "AttachedDocument":
                return self._detect_inside_attached(root)

            # Caso 5: ApplicationResponse
            if root_tag == "ApplicationResponse":
                return "ApplicationResponse"

            return "Unknown"

        except Exception:
            return "InvalidXML"

    # ==========================================================
    # DETECTAR DENTRO DE ATTACHEDDOCUMENT
    # ==========================================================
    def _detect_inside_attached(self, root):

        for elem in root.iter():
            if elem.text and "<Invoice" in elem.text:
                return "Invoice"

            if elem.text and "<CreditNote" in elem.text:
                return "CreditNote"

            if elem.text and "<DebitNote" in elem.text:
                return "DebitNote"

        return "AttachedDocument"

    # ==========================================================
    # UTILIDAD
    # ==========================================================
    def _strip_namespace(self, tag: str) -> str:
        return tag.split("}")[-1]