# FactIA - Documentacion Tecnica

## 1. Resumen tecnico

FactIA es un servicio Python/Flask ejecutado con Gunicorn que encapsula dos servicios internos:

- `historico_service`: descarga correos y adjuntos desde Microsoft Graph.
- `transformacion_service`: clasifica ZIPs, parsea XML UBL y genera metadatos.

El servicio se integra con el backend Django de `automation-hub-finagro` por HTTP. Django autentica usuarios, actua como proxy hacia FactIA, persiste facturas en base de datos y expone la API consumida por el frontend React.

## 2. Stack

| Capa | Tecnologia |
|---|---|
| Servicio ETL | Python 3.11, Flask, Gunicorn |
| Scheduler | APScheduler |
| Cliente HTTP | requests, certifi |
| Autenticacion Microsoft | OAuth2 client credentials |
| Fuente correo | Microsoft Graph API |
| XML | `xml.etree.ElementTree`, namespaces UBL `cbc` y `cac` |
| Backend portal | Django + Django REST Framework |
| Frontend portal | React |
| Automatizacion Mercurio | Playwright, procesamiento de PDFs/EML segun dependencias disponibles |
| Persistencia FactIA | Sistema de archivos en `/data/factia` |
| Persistencia portal | Modelo Django `FacturaElectronica` |

## 3. Estructura principal

```text
FactIA/
├── app.py
├── Dockerfile
├── requirements.txt
├── historico_service/
│   ├── auth.py
│   ├── config.py
│   ├── control.py
│   ├── downloader.py
│   ├── extractor.py
│   ├── graph_client.py
│   ├── logger_config.py
│   ├── main.py
│   └── storage.py
├── transformacion_service/
│   ├── classifier.py
│   ├── config.py
│   ├── main.py
│   ├── metadata_extractor.py
│   ├── metadata_writer.py
│   └── validator.py
└── descargar_service/
```

## 4. Variables de entorno

| Variable | Uso |
|---|---|
| `FACTIA_DATA_DIR` | Directorio persistente de datos. Valor por defecto: `/data/factia`. |
| `TENANT_ID` | Tenant Azure AD para OAuth2. |
| `CLIENT_ID` | Client ID de la aplicacion registrada en Azure. |
| `CLIENT_SECRET` | Secreto de aplicacion para OAuth2. |
| `BACKEND_URL` | URL interna del backend Django. Valor por defecto: `http://backend:8000`. |
| `CRON_INTERNAL_TOKEN` | Token compartido entre FactIA y Django para sincronizacion automatica. |

Constantes actuales:

| Constante | Valor |
|---|---|
| `MAILBOX` | `facturacion@finagro.com.co` |
| `START_DATE` | `2026-01-01T00:00:00Z` |
| `PAGE_SIZE` | `10` mensajes por pagina |
| `DOWNLOAD_TIMEOUT` | `90` segundos por adjunto |

## 5. Servicio historico

### 5.1 Autenticacion

Archivo: `historico_service/auth.py`

Usa OAuth2 client credentials contra:

```text
https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token
```

Parametros:

| Parametro | Valor |
|---|---|
| `client_id` | `CLIENT_ID` |
| `client_secret` | `CLIENT_SECRET` |
| `scope` | `https://graph.microsoft.com/.default` |
| `grant_type` | `client_credentials` |

### 5.2 Consulta Graph

Archivo: `historico_service/graph_client.py`

Endpoint principal:

```text
GET https://graph.microsoft.com/v1.0/users/{MAILBOX}/messages
```

Query:

```text
$filter=receivedDateTime ge {fecha_desde} [and receivedDateTime le {fecha_hasta}]
$orderby=receivedDateTime asc
$top=10
$select=id,subject,receivedDateTime,from,hasAttachments
```

Adjuntos:

```text
GET /users/{MAILBOX}/messages/{message_id}/attachments?$select=id,name,contentType,size
GET /users/{MAILBOX}/messages/{message_id}/attachments/{attachment_id}/$value
```

### 5.3 Resiliencia Graph

| Escenario | Manejo |
|---|---|
| `401` | Renueva token y reintenta una vez. |
| `429` | Respeta `Retry-After`; si no existe, usa backoff. |
| `500`, `502`, `503`, `504` | Backoff exponencial hasta 3 intentos. |
| Timeout/conexion | Reintento con backoff hasta 3 intentos. |
| Descarga lenta | Timeout duro de 90 segundos por adjunto. |

### 5.4 Descarga y deduplicacion

Archivo: `historico_service/downloader.py`

El downloader:

1. Carga `procesados.json`.
2. Pagina mensajes de Graph.
3. Omite mensajes cuyo `id` ya exista.
4. Descarga solo adjuntos `.zip`.
5. Guarda los ZIPs segun fecha de recepcion.
6. Extrae cada ZIP en `extraidos/`.
7. Persiste el mensaje en `procesados.json`.

El registro persistido por mensaje contiene:

```json
{
  "receivedDateTime": "2026-01-01T12:00:00Z",
  "subject": "Asunto",
  "from": "proveedor@dominio.com",
  "hasAttachments": true,
  "attachments": [
    {
      "filename": "factura.zip",
      "storage_path": "historico_2026/2026/01_january/semana_01"
    }
  ]
}
```

## 6. Servicio de transformacion

### 6.1 Rutas configuradas

Archivo: `transformacion_service/config.py`

| Ruta | Uso |
|---|---|
| `historico_2026` | Entrada de ZIPs originales. |
| `curado_2026` | Salida de documentos aceptados. |
| `rechazados_2026` | Salida de documentos rechazados o no facturables. |

### 6.2 Clasificacion

Archivos: `transformacion_service/classifier.py`, `validator.py`

Proceso:

1. Recorre recursivamente `historico_2026`.
2. Abre cada ZIP.
3. Localiza archivos `.xml`.
4. Detecta la raiz XML sin namespace.
5. Si la raiz es `AttachedDocument`, inspecciona el texto embebido buscando `Invoice`, `CreditNote` o `DebitNote`.
6. Decide el tipo final segun prioridad.
7. Extrae el ZIP al destino correspondiente.

Estadisticas generadas:

```json
{
  "Invoice": 0,
  "CreditNote": 0,
  "DebitNote": 0,
  "ApplicationResponse": 0,
  "AttachedDocument": 0,
  "Unknown": 0,
  "InvalidXML": 0,
  "SinXML": 0
}
```

### 6.3 Extraccion de metadatos

Archivo: `transformacion_service/metadata_extractor.py`

Entradas:

- XMLs en `curado_2026/facturas`.
- XMLs en `rechazados_2026/CreditNote`.
- PDFs en `rechazados_2026/SinXML`.
- `procesados.json` para correlacionar archivo con fecha de recepcion.

Namespaces:

| Prefix | Namespace |
|---|---|
| `cbc` | `urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2` |
| `cac` | `urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2` |

Campos generados:

| Campo | Fuente tecnica |
|---|---|
| `tipo_documento` | Raiz resuelta: `Invoice`, `CreditNote`, `DebitNote` o `SinXML`. |
| `proveedor_nit` | `.//cac:AccountingSupplierParty//cbc:CompanyID` |
| `fecha_emision` | `procesados.json` por nombre del ZIP; fallback `.//cbc:IssueDate`. |
| `fecha_vencimiento` | Ultimo dia del mes de `fecha_emision`. |
| `codigo` | Numero original sin digitos; fallback `FACT`. |
| `numero_factura` | `cbc:ID` raiz, removiendo caracteres no numericos. |
| `valor_factura` | `.//cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount`; fallback `LineExtensionAmount`. |
| `observaciones` | Texto generado: `Factura {numero} radicado ***` o `Nota Credito {numero} radicado ***`. |
| `iva_facturado_proveedor` | Suma de `cac:TaxTotal/cbc:TaxAmount` a nivel raiz. |
| `archivo` | Ruta del XML o PDF procesado. |

Salidas:

- `facturas_metadata.json`
- `metadata_facturas_2026.csv`

## 7. API FactIA

FactIA expone endpoints bajo `/api/` en el servicio Flask.

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/descargar/` | Descarga correos por rango opcional. |
| `POST` | `/api/descargar/stream/` | Descarga con logs SSE. |
| `POST` | `/api/procesar/` | Clasifica ZIPs y extrae metadatos. |
| `POST` | `/api/procesar/stream/` | Procesa con logs SSE. |
| `POST` | `/api/abort/` | Activa bandera de cancelacion. |
| `GET` | `/api/facturas/` | Retorna `facturas_metadata.json`. |
| `GET` | `/api/stats/` | Retorna estadisticas de mensajes, ZIPs y facturas. |
| `GET` | `/api/descargar-carpetas/` | Sirve `FacturasElectronicas.zip`. |
| `GET` | `/api/descargar-carpetas/info/` | Retorna informacion del ZIP cacheado. |
| `GET` | `/api/semanas/` | Lista semanas disponibles y conteos. |
| `GET` | `/api/descargar-pdfs/?semana=...` | Sirve PDFs empaquetados por semana. |
| `GET` | `/api/cron-log/` | Retorna historial de cron. |
| `POST` | `/api/cron-log/` | Registra una ejecucion cron. |
| `GET` | `/api/descargar-exe/` | Sirve ejecutable de sincronizacion si existe. |
| `GET` | `/api/health/` | Healthcheck simple. |

## 8. Integracion con Django

Modulo: `automation-hub-finagro/backend/modules/facturacion/`

| Archivo | Responsabilidad |
|---|---|
| `client.py` | Cliente HTTP hacia FactIA. |
| `views.py` | Vistas DRF, proxies SSE, sincronizacion cron, Mercurio y descargas. |
| `models.py` | Modelo `FacturaElectronica`. |
| `serializers.py` | Serializacion REST. |
| `urls.py` | Rutas publicadas bajo `/api/facturacion/`. |

Modelo principal:

```text
FacturaElectronica
├── execution
├── tipo_documento
├── proveedor_nit
├── numero_factura
├── codigo
├── valor_factura
├── iva_facturado_proveedor
├── fecha_emision
├── fecha_vencimiento
├── observaciones
├── archivo
└── procesado_en
```

Restriccion unica:

```text
(tipo_documento, proveedor_nit, numero_factura)
```

## 9. Scheduler

FactIA usa `BackgroundScheduler` con zona horaria `America/Bogota`.

| Slot | Rango UTC calculado |
|---|---|
| `06:00` | Desde 21:00 UTC del dia anterior hasta 11:00 UTC del dia actual. |
| `11:00` | Desde 11:00 UTC hasta 16:00 UTC del dia actual. |
| `16:00` | Desde 16:00 UTC hasta 21:00 UTC del dia actual. |

Cada slot ejecuta:

1. `_historico_con_conteo(fecha_desde, fecha_hasta)`
2. `_procesar_completo()`
3. `POST {BACKEND_URL}/api/facturacion/sincronizar-cron/`
4. Escritura en `cron_log.json`

## 10. Despliegue

Dockerfile:

```text
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data/factia
ENV FACTIA_DATA_DIR=/data/factia
CMD ["gunicorn", "--bind", "0.0.0.0:8002", "--timeout", "600", "--workers", "1", "app:app"]
```

Notas:

- Se usa un worker Gunicorn para evitar duplicar el scheduler interno.
- El timeout de Gunicorn es 600 segundos por descargas/procesos largos.
- `/data/factia` debe montarse como volumen persistente.

## 11. Observabilidad y control

| Mecanismo | Descripcion |
|---|---|
| Logs Python | Se emiten a consola y a SSE durante jobs manuales. |
| SSE | Transmite `data:`, `event: result` y `event: error`. |
| `cron_log.json` | Conserva las ultimas 50 ejecuciones programadas. |
| `Execution` y `ExecutionLog` | Django registra ejecuciones manuales y logs funcionales. |
| `/api/health/` | Verificacion basica del servicio Flask. |
| `/api/facturacion/stats/` | Estadisticas operativas desde FactIA. |

## 12. Riesgos tecnicos y consideraciones

| Riesgo | Consideracion |
|---|---|
| Scheduler dentro de Flask | Mantener un solo worker para no ejecutar jobs duplicados. |
| Persistencia en JSON | `procesados.json`, `facturas_metadata.json` y `cron_log.json` son archivos criticos; requieren backup del volumen. |
| Reprocesamiento completo | El clasificador recorre `historico_2026` completo en cada proceso. |
| Credenciales | `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET` y `CRON_INTERNAL_TOKEN` deben gestionarse como secretos. |
| XML heterogeneo | AttachedDocument y documentos DIAN pueden variar; el extractor contempla CDATA y fallback de fecha. |
| Mercurio | El scraping depende de estructura HTML, disponibilidad del portal y dependencias runtime. |

