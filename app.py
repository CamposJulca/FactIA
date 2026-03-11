"""
FactIA — REST API wrapper
Expone los servicios historico_service y transformacion_service via HTTP.
Incluye endpoints de streaming SSE para mostrar progreso en tiempo real.
"""
import os
import json
import logging
import threading
import queue as _queue
from collections import Counter

from flask import Flask, jsonify, request, Response, stream_with_context

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

CURATED_FOLDER  = 'curado_2026/facturas'
PROCESADOS_FILE = os.path.join(DATA_DIR, 'procesados.json')
FACTURAS_FILE   = os.path.join(DATA_DIR, 'facturas_metadata.json')

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger('factia')

app = Flask(__name__)

# Evento de abort — compartido entre el endpoint /api/abort/ y los jobs en ejecución
_abort_event = threading.Event()


# ── Streaming helper ──────────────────────────────────────────────────────────

class _QueueHandler(logging.Handler):
    """Handler que envía cada línea de log a una queue."""
    def __init__(self, q):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            self.q.put(('log', self.format(record)))
        except Exception:
            pass


def _stream_job(fn, kwargs=None):
    """
    Ejecuta fn(**kwargs) en un hilo secundario.
    Captura todo el output de logging via root logger y lo emite como SSE.
    Al terminar emite un evento 'result' o 'error'.
    """
    kwargs = kwargs or {}
    q        = _queue.Queue()
    handler  = _QueueHandler(q)
    handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s'))

    root = logging.getLogger()
    root.addHandler(handler)

    result_box = {}

    def _run():
        try:
            result_box['data'] = fn(**kwargs)
            result_box['ok']   = True
        except Exception as exc:
            result_box['ok']    = False
            result_box['error'] = str(exc)
        finally:
            root.removeHandler(handler)
            q.put(('__done__', None))

    threading.Thread(target=_run, daemon=True).start()

    while True:
        try:
            kind, payload = q.get(timeout=5)
        except _queue.Empty:
            # Hilo sigue corriendo pero sin logs en este momento
            # Emitir comentario SSE para mantener viva la conexión (evita timeout Nginx)
            yield ": keep-alive\n\n"
            continue

        if kind == '__done__':
            break
        yield f"data: {payload}\n\n"

    if result_box.get('ok'):
        yield f"event: result\ndata: {json.dumps(result_box['data'])}\n\n"
    else:
        error_msg = result_box.get('error', 'Error desconocido')
        yield f"event: error\ndata: {error_msg}\n\n"


# ── Wrappers que retornan dict ────────────────────────────────────────────────

def _historico_con_conteo(fecha_desde=None, fecha_hasta=None):
    _run_historico(fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, abort_event=_abort_event)
    count = 0
    if os.path.exists(PROCESADOS_FILE):
        with open(PROCESADOS_FILE, 'r', encoding='utf-8') as f:
            count = len(json.load(f))
    aborted = _abort_event.is_set()
    return {'status': 'aborted' if aborted else 'ok', 'mensajes_procesados': count}


def _procesar_completo():
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

    return {
        'status':        'ok',
        'clasificacion': stats,
        'facturas':      facturas,
        'total':         len(facturas),
        'errores':       extractor.errores,
    }


# ── Endpoints clásicos (sin streaming) ───────────────────────────────────────

@app.route('/api/abort/', methods=['POST'])
def abort_job():
    """Activa el evento de abort para detener el job en curso limpiamente."""
    _abort_event.set()
    log.warning('Abort solicitado por el usuario.')
    return jsonify({'status': 'abort_requested'})


@app.route('/api/descargar/', methods=['POST'])
def descargar():
    try:
        body        = request.get_json(silent=True) or {}
        fecha_desde = body.get('fecha_desde')
        fecha_hasta = body.get('fecha_hasta')
        data = _historico_con_conteo(fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
        return jsonify(data)
    except Exception as exc:
        log.error(f'Error en descarga: {exc}')
        return jsonify({'error': str(exc)}), 500


@app.route('/api/procesar/', methods=['POST'])
def procesar():
    try:
        data = _procesar_completo()
        return jsonify(data)
    except Exception as exc:
        log.error(f'Error en procesamiento: {exc}')
        return jsonify({'error': str(exc)}), 500


# ── Endpoints streaming SSE ───────────────────────────────────────────────────

@app.route('/api/descargar/stream/', methods=['POST'])
def descargar_stream():
    """
    Igual que /api/descargar/ pero emite cada línea de log como SSE en tiempo real.
    Evento final: 'result' con JSON de resumen, o 'event: error' con el mensaje.
    """
    body        = request.get_json(silent=True) or {}
    fecha_desde = body.get('fecha_desde')
    fecha_hasta = body.get('fecha_hasta')

    # Limpiar el evento de abort antes de iniciar
    _abort_event.clear()

    @stream_with_context
    def generate():
        yield from _stream_job(
            _historico_con_conteo,
            kwargs={'fecha_desde': fecha_desde, 'fecha_hasta': fecha_hasta},
        )

    return Response(
        generate(),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/api/procesar/stream/', methods=['POST'])
def procesar_stream():
    """
    Igual que /api/procesar/ pero emite cada línea de log como SSE en tiempo real.
    """
    @stream_with_context
    def generate():
        yield from _stream_job(_procesar_completo)

    return Response(
        generate(),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# ── Endpoints de consulta ─────────────────────────────────────────────────────

@app.route('/api/facturas/', methods=['GET'])
def listar_facturas():
    try:
        if not os.path.exists(FACTURAS_FILE):
            return jsonify({'facturas': [], 'total': 0})
        with open(FACTURAS_FILE, 'r', encoding='utf-8') as f:
            facturas = json.load(f)
        return jsonify({'facturas': facturas, 'total': len(facturas)})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/api/stats/', methods=['GET'])
def stats():
    """Retorna estadísticas de descarga: conteo de mensajes por mes y rango de fechas."""
    try:
        if not os.path.exists(PROCESADOS_FILE):
            return jsonify({'total_mensajes': 0, 'fecha_min': None, 'fecha_max': None, 'por_mes': []})

        with open(PROCESADOS_FILE, 'r', encoding='utf-8') as f:
            procesados = json.load(f)

        if not procesados:
            return jsonify({'total_mensajes': 0, 'fecha_min': None, 'fecha_max': None, 'por_mes': []})

        fechas = [v['receivedDateTime'] for v in procesados.values() if v.get('receivedDateTime')]
        fecha_min = min(fechas) if fechas else None
        fecha_max = max(fechas) if fechas else None

        por_mes_zips    = Counter()   # ZIPs descargados por mes
        por_mes_correos = Counter()   # correos con al menos 1 ZIP por mes
        total_zips = 0

        for v in procesados.values():
            atts = v.get('attachments', [])
            if not atts:
                continue  # correo sin ZIP — no se cuenta
            dt = v.get('receivedDateTime', '')
            mes = dt[:7] if dt else 'desconocido'
            por_mes_correos[mes] += 1
            por_mes_zips[mes]    += len(atts)
            total_zips           += len(atts)

        # Rango de fechas considerando solo los correos con ZIPs
        fechas_con_zip = [
            v['receivedDateTime']
            for v in procesados.values()
            if v.get('attachments') and v.get('receivedDateTime')
        ]
        fecha_min_zip = min(fechas_con_zip) if fechas_con_zip else None
        fecha_max_zip = max(fechas_con_zip) if fechas_con_zip else None

        all_meses = sorted(set(list(por_mes_zips.keys()) + list(por_mes_correos.keys())))
        por_mes = [
            {
                'mes':     m,
                'correos': por_mes_correos[m],
                'zips':    por_mes_zips[m],
            }
            for m in all_meses
        ]

        return jsonify({
            'total_mensajes': len(procesados),
            'total_con_zip':  sum(por_mes_correos.values()),
            'total_zips':     total_zips,
            'fecha_min':      fecha_min_zip,
            'fecha_max':      fecha_max_zip,
            'por_mes':        por_mes,
        })
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/api/health/', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8002, debug=False)
