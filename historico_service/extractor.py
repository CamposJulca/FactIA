"""
Extrae archivos de un ZIP descargado a una carpeta local.
Mantiene la misma jerarquía de directorios que el histórico:
  extraidos/{año}/{mes}/{semana}/nombre_zip/
"""
import os
import zipfile
import logging

log = logging.getLogger(__name__)


def extraer_zip(zip_path: str, dest_base: str) -> str | None:
    """
    Extrae `zip_path` en `dest_base/{carpeta_relativa}/{nombre_sin_ext}/`.

    La carpeta relativa se calcula a partir de la ruta del ZIP conservando
    la misma estructura que el histórico:
      historico_2026/2026/01_january/semana_01/archivo.zip
      → extraidos/2026/01_january/semana_01/archivo/

    Returns:
        Ruta de la carpeta de destino, o None si falla.
    """
    try:
        zip_path = os.path.abspath(zip_path)
        # Nombre del ZIP sin extensión → carpeta de destino
        nombre_sin_ext = os.path.splitext(os.path.basename(zip_path))[0]

        # Directorio padre del ZIP (semana_XX)
        semana_dir = os.path.dirname(zip_path)
        # Subir hasta encontrar el directorio raíz del histórico
        # Estructura: historico_2026/2026/mm_month/semana_XX/archivo.zip
        # Queremos conservar 2026/mm_month/semana_XX como ruta relativa
        parts = semana_dir.replace('\\', '/').split('/')
        # Buscar el segmento de año (4 dígitos)
        try:
            idx_year = next(i for i, p in enumerate(parts) if p.isdigit() and len(p) == 4)
            rel_path = os.path.join(*parts[idx_year:])
        except StopIteration:
            rel_path = os.path.basename(semana_dir)

        dest_dir = os.path.join(dest_base, rel_path, nombre_sin_ext)
        os.makedirs(dest_dir, exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(dest_dir)

        log.info(f"ZIP extraído → {dest_dir} ({len(zf.namelist())} archivos)")
        return dest_dir

    except zipfile.BadZipFile:
        log.warning(f"Archivo no es un ZIP válido: {zip_path}")
        return None
    except Exception as exc:
        log.error(f"Error extrayendo {zip_path}: {exc}")
        return None
