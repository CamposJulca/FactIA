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
from datetime import datetime, timedelta, timezone

import requests as _reqs
from flask import Flask, jsonify, request, Response, stream_with_context
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

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
CRON_LOG_FILE   = os.path.join(DATA_DIR, 'cron_log.json')

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

        total_facturas_extraidas = 0
        if os.path.exists(FACTURAS_FILE):
            try:
                with open(FACTURAS_FILE, 'r', encoding='utf-8') as fmeta:
                    total_facturas_extraidas = len(json.load(fmeta))
            except Exception:
                pass

        return jsonify({
            'total_mensajes':          len(procesados),
            'total_con_zip':           sum(por_mes_correos.values()),
            'total_zips':              total_zips,
            'total_facturas_extraidas': total_facturas_extraidas,
            'fecha_min':               fecha_min_zip,
            'fecha_max':               fecha_max_zip,
            'por_mes':                 por_mes,
        })
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/api/descargar-carpetas/', methods=['GET'])
def descargar_carpetas():
    """
    GET /api/descargar-carpetas/?actualizar=1
    Extrae todos los ZIPs del histórico a carpetas y sirve un ZIP descargable.
    - Sin parámetros: sirve el ZIP cacheado si existe y está actualizado.
    - ?actualizar=1: re-extrae todos los ZIPs nuevos y regenera el ZIP.
    """
    import glob, zipfile as _zipfile, tempfile
    from flask import send_file

    HISTORICO    = os.path.join(DATA_DIR, 'historico_2026')
    EXTRAIDOS    = os.path.join(DATA_DIR, 'extraidos')
    ZIP_CACHE    = os.path.join(DATA_DIR, 'FacturasElectronicas.zip')
    actualizar   = request.args.get('actualizar', '0') == '1'

    os.makedirs(EXTRAIDOS, exist_ok=True)

    # ── Extraer ZIPs nuevos o todos si se pide actualización ─────────────────
    zips = sorted(glob.glob(f'{HISTORICO}/**/*.zip', recursive=True))
    ok = skip = err = 0
    for zip_path in zips:
        rel     = os.path.relpath(os.path.dirname(zip_path), HISTORICO)
        nombre  = os.path.splitext(os.path.basename(zip_path))[0]
        dest    = os.path.join(EXTRAIDOS, rel, nombre)
        if not actualizar and os.path.exists(dest) and os.listdir(dest):
            skip += 1
            continue
        os.makedirs(dest, exist_ok=True)
        try:
            with _zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(dest)
            ok += 1
        except Exception as exc:
            log.warning(f'Error extrayendo {zip_path}: {exc}')
            err += 1

    log.info(f'Extracción: {ok} nuevos | {skip} ya existían | {err} errores')

    # ── Regenerar ZIP cacheado si hubo cambios o se pidió actualización ───────
    if ok > 0 or actualizar or not os.path.exists(ZIP_CACHE):
        log.info('Generando FacturasElectronicas.zip...')
        tmp_path = ZIP_CACHE + '.tmp'
        with _zipfile.ZipFile(tmp_path, 'w', _zipfile.ZIP_DEFLATED) as zout:
            for root, dirs, files in os.walk(EXTRAIDOS):
                for fname in files:
                    fpath   = os.path.join(root, fname)
                    arcname = os.path.relpath(fpath, EXTRAIDOS)
                    zout.write(fpath, arcname)
        os.replace(tmp_path, ZIP_CACHE)
        log.info(f'ZIP generado: {os.path.getsize(ZIP_CACHE) // (1024*1024)} MB')

    return send_file(
        ZIP_CACHE,
        mimetype='application/zip',
        as_attachment=True,
        download_name='FacturasElectronicas.zip',
    )


@app.route('/api/descargar-carpetas/info/', methods=['GET'])
def descargar_carpetas_info():
    """
    GET /api/descargar-carpetas/info/
    Retorna metadatos del ZIP cacheado sin descargarlo.
    """
    import glob
    HISTORICO = os.path.join(DATA_DIR, 'historico_2026')
    EXTRAIDOS = os.path.join(DATA_DIR, 'extraidos')
    ZIP_CACHE = os.path.join(DATA_DIR, 'FacturasElectronicas.zip')

    total_zips     = len(glob.glob(f'{HISTORICO}/**/*.zip', recursive=True))
    total_carpetas = sum(1 for d in os.scandir(EXTRAIDOS) if d.is_dir()) if os.path.exists(EXTRAIDOS) else 0
    zip_info       = {}
    if os.path.exists(ZIP_CACHE):
        st = os.stat(ZIP_CACHE)
        zip_info = {
            'size_mb':   round(st.st_size / (1024 * 1024), 1),
            'generado':  __import__('datetime').datetime.fromtimestamp(st.st_mtime).isoformat(),
        }

    return jsonify({
        'total_zips':     total_zips,
        'total_carpetas': total_carpetas,
        'cache':          zip_info,
    })


@app.route('/api/semanas/', methods=['GET'])
def listar_semanas():
    """
    GET /api/semanas/
    Retorna la lista de semanas disponibles en el histórico.
    - total_zips : ZIPs crudos descargados del buzón
    - total_pdfs : PDFs en extraidos/ (todos los extraídos, incluyendo notas crédito, etc.)
                   Se sincronizan ZIPs faltantes antes de contar.
    """
    import glob as _glob, zipfile as _zipfile
    HISTORICO = os.path.join(DATA_DIR, 'historico_2026')
    EXTRAIDOS = os.path.join(DATA_DIR, 'extraidos')

    semanas_zips = {}

    for zip_path in _glob.glob(f'{HISTORICO}/**/*.zip', recursive=True):
        rel   = os.path.relpath(zip_path, HISTORICO)
        parts = rel.replace('\\', '/').split('/')
        if len(parts) >= 3:
            key = '/'.join(parts[:3])
            semanas_zips[key] = semanas_zips.get(key, 0) + 1

            # Extraer al vuelo si la carpeta del ZIP no existe aún en extraidos/
            zip_stem = os.path.splitext(parts[-1])[0]
            dest = os.path.join(EXTRAIDOS, key, zip_stem)
            if not os.path.exists(dest) or not os.listdir(dest):
                os.makedirs(dest, exist_ok=True)
                try:
                    with _zipfile.ZipFile(zip_path, 'r') as zf:
                        zf.extractall(dest)
                except Exception as exc:
                    log.warning(f'listar_semanas: error extrayendo {zip_path}: {exc}')

    # Contar PDFs por semana desde extraidos/ (ya sincronizado)
    semanas_pdfs = {}
    if os.path.exists(EXTRAIDOS):
        for root, dirs, files in os.walk(EXTRAIDOS):
            pdfs = sum(1 for f in files if f.lower().endswith('.pdf'))
            if not pdfs:
                continue
            rel   = os.path.relpath(root, EXTRAIDOS)
            parts = rel.replace('\\', '/').split('/')
            if len(parts) >= 3:
                key = '/'.join(parts[:3])
                semanas_pdfs[key] = semanas_pdfs.get(key, 0) + pdfs

    all_keys = sorted(set(list(semanas_zips.keys()) + list(semanas_pdfs.keys())))
    result = []
    for key in all_keys:
        parts = key.split('/')
        result.append({
            'key':        key,
            'year':       parts[0],
            'mes':        parts[1],
            'semana':     parts[2],
            'total_zips': semanas_zips.get(key, 0),
            'total_pdfs': semanas_pdfs.get(key, 0),
        })
    return jsonify({'semanas': result})


@app.route('/api/descargar-pdfs/', methods=['GET'])
def descargar_pdfs():
    """
    GET /api/descargar-pdfs/?semana=2026/01_january/semana_01
    Sirve todos los PDFs de extraidos/ para la semana indicada.
    Sincroniza ZIPs faltantes antes de servir para garantizar consistencia.
    PDFs con metadata se renombran {fecha_emision}_{nit}_{num}.pdf; los demás
    conservan el nombre original.
    """
    import glob as _glob, zipfile as _zipfile, io, re

    semana = request.args.get('semana', '').strip().strip('/')
    if not semana or semana.count('/') != 2:
        return jsonify({'error': 'Parámetro semana inválido. Formato: 2026/01_january/semana_01'}), 400

    HISTORICO  = os.path.join(DATA_DIR, 'historico_2026')
    EXTRAIDOS  = os.path.join(DATA_DIR, 'extraidos')
    semana_dir = os.path.join(EXTRAIDOS, semana)
    semana_src = os.path.join(HISTORICO, semana)

    if not os.path.isdir(semana_src):
        return jsonify({'error': f'Semana no encontrada: {semana}'}), 404

    # Sincronizar: extraer cualquier ZIP que aún no tenga carpeta en extraidos/
    for zip_path in sorted(_glob.glob(os.path.join(semana_src, '*.zip'))):
        zip_stem = os.path.splitext(os.path.basename(zip_path))[0]
        dest = os.path.join(semana_dir, zip_stem)
        if not os.path.exists(dest) or not os.listdir(dest):
            os.makedirs(dest, exist_ok=True)
            try:
                with _zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(dest)
            except Exception as exc:
                log.warning(f'descargar_pdfs: error extrayendo {zip_path}: {exc}')

    if not os.path.isdir(semana_dir):
        return jsonify({'error': f'No se pudo preparar la semana: {semana}'}), 500

    # Construir índice metadata: nombre_carpeta_zip → factura
    meta_index = {}
    if os.path.exists(FACTURAS_FILE):
        with open(FACTURAS_FILE, 'r', encoding='utf-8') as f:
            for factura in json.load(f):
                archivo = factura.get('archivo', '').replace('\\', '/')
                partes  = archivo.split('/')
                if len(partes) >= 2:
                    meta_index[partes[-2]] = factura

    buf = io.BytesIO()
    agregados = 0
    nombres_usados = set()
    with _zipfile.ZipFile(buf, 'w', _zipfile.ZIP_DEFLATED) as zout:
        for entry in sorted(os.scandir(semana_dir), key=lambda e: e.name):
            if not entry.is_dir():
                continue
            zip_stem = entry.name
            meta     = meta_index.get(zip_stem)
            # Buscar PDFs recursivamente dentro de la carpeta del ZIP
            for root, dirs, files in os.walk(entry.path):
                for fname in sorted(files):
                    if not fname.lower().endswith('.pdf'):
                        continue
                    pdf_path = os.path.join(root, fname)
                    with open(pdf_path, 'rb') as pf:
                        pdf_data = pf.read()
                    if meta:
                        fecha = meta.get('fecha_emision') or 'sin_fecha'
                        nit   = re.sub(r'[^\w]', '_', str(meta.get('proveedor_nit', 'nit')))
                        num   = re.sub(r'[^\w\-]', '_', str(meta.get('numero_factura', '0')))
                        nombre_final = f"{fecha}_{nit}_{num}.pdf"
                    else:
                        nombre_final = fname
                    # Evitar colisiones de nombre en el ZIP
                    base, ext = os.path.splitext(nombre_final)
                    candidato = nombre_final
                    contador  = 1
                    while candidato in nombres_usados:
                        candidato = f"{base}_{contador}{ext}"
                        contador += 1
                    nombres_usados.add(candidato)
                    zout.writestr(candidato, pdf_data)
                    agregados += 1

    buf.seek(0)
    semana_label = semana.replace('/', '_')
    return Response(
        buf.read(),
        mimetype='application/zip',
        headers={
            'Content-Disposition': f'attachment; filename="PDFs_{semana_label}.zip"',
            'X-Total-PDFs': str(agregados),
        },
    )


@app.route('/api/cron-log/', methods=['GET'])
def get_cron_log():
    """Retorna el historial de ejecuciones programadas."""
    try:
        if not os.path.exists(CRON_LOG_FILE):
            return jsonify({'runs': []})
        with open(CRON_LOG_FILE, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/api/cron-log/', methods=['POST'])
def post_cron_log():
    """Registra el resultado de una ejecución programada."""
    try:
        body = request.get_json(silent=True) or {}
        _write_cron_log(body)
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/api/descargar-exe/', methods=['GET'])
def descargar_exe():
    """Sirve SincronizarFacturas.exe si fue compilado con build.sh."""
    from flask import send_file, abort
    exe_path = os.path.join(DATA_DIR, 'SincronizarFacturas.exe')
    if not os.path.isfile(exe_path):
        abort(404)
    return send_file(
        exe_path,
        as_attachment=True,
        download_name='SincronizarFacturas.exe',
        mimetype='application/octet-stream',
    )


@app.route('/api/health/', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


# ── Helper cron log ───────────────────────────────────────────────────────────

def _write_cron_log(entry: dict):
    """Inserta una entrada al historial de cron, conservando las últimas 50."""
    data = {}
    if os.path.exists(CRON_LOG_FILE):
        try:
            with open(CRON_LOG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
    runs = data.get('runs', [])
    runs.insert(0, entry)
    runs = runs[:50]
    with open(CRON_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump({'runs': runs}, f, ensure_ascii=False)


# ── Cron automático ───────────────────────────────────────────────────────────

BOGOTA_TZ = pytz.timezone('America/Bogota')

def _run_cron_slot(hora_slot: str):
    """
    Ejecuta el pipeline completo para el slot horario indicado.
    Calcula el rango de fechas en UTC (Colombia = UTC-5, sin DST).
    Slots:
        06:00  → 4 PM ayer - 6 AM hoy  (UTC: ayer 21:00 - hoy 11:00)
        11:00  → 6 AM hoy - 11 AM hoy  (UTC: hoy 11:00 - hoy 16:00)
        16:00  → 11 AM hoy - 4 PM hoy  (UTC: hoy 16:00 - hoy 21:00)
    """
    log.info(f'[CRON] Iniciando slot {hora_slot}')
    now_utc  = datetime.now(timezone.utc)
    today    = now_utc.date()
    yesterday = today - timedelta(days=1)

    if hora_slot == '06:00':
        f_desde = f'{yesterday}T21:00:00Z'
        f_hasta = f'{today}T11:00:00Z'
    elif hora_slot == '11:00':
        f_desde = f'{today}T11:00:00Z'
        f_hasta = f'{today}T16:00:00Z'
    else:  # 16:00
        f_desde = f'{today}T16:00:00Z'
        f_hasta = f'{today}T21:00:00Z'

    status_final   = 'error'
    mensajes_proc  = 0
    facturas_guard = 0
    errores        = 0

    try:
        # Paso 1 — Descargar correos del rango
        res_desc = _historico_con_conteo(fecha_desde=f_desde, fecha_hasta=f_hasta)
        mensajes_proc = res_desc.get('mensajes_procesados', 0)
        log.info(f'[CRON {hora_slot}] Descarga OK — {mensajes_proc} mensajes totales')

        # Paso 2 — Clasificar y extraer metadata
        res_proc = _procesar_completo()
        errores  = res_proc.get('errores', 0)
        log.info(f'[CRON {hora_slot}] Procesamiento OK — {res_proc.get("total", 0)} facturas, {errores} errores')

        # Paso 3 — Sincronizar con Django DB
        backend_url  = os.getenv('BACKEND_URL', 'http://backend:8000')
        cron_token   = os.getenv('CRON_INTERNAL_TOKEN', '')
        if cron_token:
            sync_resp = _reqs.post(
                f'{backend_url}/api/facturacion/sincronizar-cron/',
                headers={'X-Cron-Token': cron_token},
                timeout=120,
            )
            if sync_resp.status_code == 200:
                facturas_guard = sync_resp.json().get('total', 0)
                log.info(f'[CRON {hora_slot}] Sync DB OK — {facturas_guard} facturas guardadas')
                status_final = 'ok'
            else:
                log.error(f'[CRON {hora_slot}] Sync DB error {sync_resp.status_code}')
        else:
            log.warning(f'[CRON {hora_slot}] CRON_INTERNAL_TOKEN no configurado — omitiendo sync DB')
            status_final = 'ok'

    except Exception as exc:
        log.error(f'[CRON {hora_slot}] Fallo: {exc}')

    _write_cron_log({
        'timestamp':         datetime.now().isoformat(),
        'status':            status_final,
        'hora_slot':         hora_slot,
        'mensajes_procesados': mensajes_proc,
        'facturas_guardadas':  facturas_guard,
        'errores':           errores,
        'rango':             f'{f_desde} → {f_hasta}',
    })
    log.info(f'[CRON {hora_slot}] Finalizado con status={status_final}')


# Iniciar scheduler (solo en proceso principal, no en reloader de Flask)
_scheduler = BackgroundScheduler(timezone=BOGOTA_TZ)
_scheduler.add_job(lambda: _run_cron_slot('06:00'), CronTrigger(hour=6,  minute=0, timezone=BOGOTA_TZ))
_scheduler.add_job(lambda: _run_cron_slot('11:00'), CronTrigger(hour=11, minute=0, timezone=BOGOTA_TZ))
_scheduler.add_job(lambda: _run_cron_slot('16:00'), CronTrigger(hour=16, minute=0, timezone=BOGOTA_TZ))
_scheduler.start()
log.info('[CRON] Scheduler iniciado — slots 06:00 | 11:00 | 16:00 (Bogotá)')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8002, debug=False)
