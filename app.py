"""
FactIA — REST API wrapper
Expone los servicios historico_service y transformacion_service via HTTP.
"""
import os
import json
import logging

from flask import Flask, jsonify

# Directorio de datos persistentes (montado como volumen en Docker)
DATA_DIR = os.getenv('FACTIA_DATA_DIR', '/data/factia')
os.makedirs(DATA_DIR, exist_ok=True)

# Todos los servicios usan rutas relativas al CWD
os.chdir(DATA_DIR)

import sys
sys.path.insert(0, '/app')

from historico_service.main import main as _run_historico
from transformacion_service.classifier import ZipClassifier
from transformacion_service.metadata_extractor import InvoiceMetadataExtractor

CURATED_FOLDER = 'curado_2026/facturas'
PROCESADOS_FILE = os.path.join(DATA_DIR, 'procesados.json')
FACTURAS_FILE   = os.path.join(DATA_DIR, 'facturas_metadata.json')
CSV_FILE        = os.path.join(DATA_DIR, 'metadata_facturas_2026.csv')

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger('factia')

app = Flask(__name__)


@app.route('/api/descargar/', methods=['POST'])
def descargar():
    """
    Descarga ZIPs de facturas desde el buzón de correo (Microsoft Graph).
    Puede tardar varios minutos dependiendo del volumen de correos.
    """
    try:
        log.info('Iniciando descarga del histórico de correos...')
        _run_historico()

        count = 0
        if os.path.exists(PROCESADOS_FILE):
            with open(PROCESADOS_FILE, 'r', encoding='utf-8') as f:
                count = len(json.load(f))

        log.info(f'Descarga finalizada. Mensajes en histórico: {count}')
        return jsonify({'status': 'ok', 'mensajes_procesados': count})

    except Exception as exc:
        log.error(f'Error en descarga: {exc}')
        return jsonify({'error': str(exc)}), 500


@app.route('/api/procesar/', methods=['POST'])
def procesar():
    """
    Clasifica los ZIPs descargados y extrae metadata de las facturas XML.
    Retorna la lista completa de facturas procesadas.
    """
    try:
        log.info('Iniciando clasificación de ZIPs...')
        classifier = ZipClassifier()
        classifier.process_all()
        stats = {'total_zips': classifier.total, **classifier.stats}
        log.info(f'Clasificación completada: {stats}')

        log.info('Iniciando extracción de metadata...')
        extractor = InvoiceMetadataExtractor(CURATED_FOLDER)
        extractor.process_all()
        log.info(f'Extracción completada: {extractor.total} facturas, {extractor.errores} errores')

        facturas = []
        if os.path.exists(FACTURAS_FILE):
            with open(FACTURAS_FILE, 'r', encoding='utf-8') as f:
                facturas = json.load(f)

        return jsonify({
            'status': 'ok',
            'clasificacion': stats,
            'facturas': facturas,
            'total': len(facturas),
            'errores': extractor.errores,
        })

    except Exception as exc:
        log.error(f'Error en procesamiento: {exc}')
        return jsonify({'error': str(exc)}), 500


@app.route('/api/facturas/', methods=['GET'])
def listar_facturas():
    """Retorna las facturas ya procesadas desde facturas_metadata.json."""
    try:
        if not os.path.exists(FACTURAS_FILE):
            return jsonify({'facturas': [], 'total': 0})

        with open(FACTURAS_FILE, 'r', encoding='utf-8') as f:
            facturas = json.load(f)

        return jsonify({'facturas': facturas, 'total': len(facturas)})

    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/api/health/', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8002, debug=False)
