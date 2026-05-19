# FactIA — Facturación Electrónica
## De la gestión manual de correos a la inteligencia documental automatizada.

---

## El Desafío Institucional

La gestión de facturas electrónicas en Finagro operaba bajo un modelo completamente manual, fragmentado y sin trazabilidad:

**La Carga Operativa:** Cada factura enviada por un proveedor al buzón `facturacion@finagro.com.co` debía ser abierta manualmente por un funcionario, el adjunto ZIP descargado, descomprimido, el archivo XML interpretado y los datos transcritos a sistemas internos. Un proceso repetitivo, propenso a errores y sin auditoría real.

**La Realidad:** La acumulación de correos sin procesar, los documentos duplicados, la imposibilidad de rastrear el origen de una factura y la ausencia de un registro consolidado generaban demoras en los procesos de pago, riesgos de doble radicación y dependencia de personal operativo para tareas puramente mecánicas.

---

## Propuesta de Valor

Hoy FactIA no solo automatiza la descarga de correos, está redefiniendo el modelo de gestión documental de Finagro, logrando un pipeline ETL completamente autónomo que opera **tres veces al día** en horarios de negocio, sin intervención humana.

Esta transformación ha eliminado por completo la transcripción manual de facturas, pasando de una gestión artesanal a un sistema con **deduplicación automática por ID de mensaje**, **clasificación inteligente de documentos DIAN** y **extracción estructurada de metadatos UBL 2.1**, todo con trazabilidad completa desde el correo electrónico hasta el registro en base de datos.

---

## Tabla de Dimensiones

| DIMENSIÓN | SITUACIÓN ANTERIOR | ESTADO ACTUAL | IMPACTO |
|---|---|---|---|
| **Operativa (Gestión Documental)** | Descarga manual de correos, descompresión artesanal de ZIPs y transcripción de datos a sistemas internos. Sin horario definido, sin trazabilidad. | Pipeline ETL automatizado ejecutándose a las **6:00 AM, 11:00 AM y 4:00 PM** (hora Bogotá). Sin intervención humana. | Eliminación total de la carga operativa manual. El equipo de tesorería ya no opera como digitalizador de documentos. |
| **Control y Riesgo** | Sin deduplicación. El mismo correo podía procesarse múltiples veces si era reenviado o si el proceso fallaba. Sin clasificación: facturas, notas crédito, respuestas DIAN mezcladas sin distinción. | Deduplicación por `message_id` de Microsoft Graph. Clasificación automática en 7 tipos documentales. Solo las facturas UBL válidas avanzan al pipeline. | **Cero duplicados** en la base de datos. Cada factura tiene un único origen rastreable hasta el correo de entrada. |
| **Tiempos de Ejecución ETL** | No medibles. El proceso dependía de la disponibilidad y velocidad del funcionario. Tiempos históricos: sin registro. | **Fase E (Extracción):** ~2-15 min según volumen. **Fase T (Transformación):** <2 min por lote completo. Tres ejecuciones diarias totalmente automáticas. | Reducción del tiempo de radicación de horas a minutos. Las facturas del día están disponibles para consulta antes del cierre de jornada. |
| **Talento y Capacidad** | Funcionarios del área de tesorería dedicando tiempo productivo a la descarga, descompresión y transcripción manual de documentos XML. | Personal liberado de la operatividad. El sistema opera en segundo plano. El equipo se enfoca en análisis, validación y decisiones de pago. | Reasignación del capital humano hacia tareas de alto valor. La operatividad documental ya no consume capacidad analítica. |
| **Trazabilidad y Auditoría** | Imposible reconstruir el camino de una factura. Sin registro de quién la procesó, cuándo llegó ni qué correo la contenía. | Cada factura tiene origen rastreable: `message_id` → `receivedDateTime` → `subject` → `from` → nombre del ZIP → ruta en disco → metadatos extraídos. | **Auditoría completa**. Es posible responder en segundos: *¿cuándo llegó esta factura, quién la envió y qué contiene el ZIP original?* |
| **Calidad del Dato** | Transcripción manual → errores en NIT, valores, prefijos de factura. Sin estándar de formato. | Extracción automática vía XPath sobre XML UBL 2.1. Los campos NIT, valor, IVA, número y código se leen directamente del estándar DIAN. | Calidad de dato garantizada por el estándar. Los errores de transcripción son técnicamente imposibles. |

---

## Pipeline ETL — Detalle Técnico por Fase

### Arquitectura General

```
[Microsoft 365 — facturacion@finagro.com.co]
          │
          ▼
┌─────────────────────────────┐
│  FASE E — EXTRACCIÓN        │  historico_service/
│  OAuth2 → Graph API → ZIP   │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  FASE T — TRANSFORMACIÓN    │  transformacion_service/
│  Clasificación + Metadatos  │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  BASE DE DATOS OPERATIVA    │  facturas_metadata.json
│  + Sincronización al portal │  → POST /api/facturacion/
└─────────────────────────────┘
```

---

### FASE E — Extracción

**Responsable:** `historico_service/`
**Disparador:** Cron automático (06:00, 11:00, 16:00 hora Bogotá) o ejecución manual desde el portal.

#### Sub-fases y tiempos de ejecución

| Sub-fase | Descripción | Tiempo estimado | Notas |
|---|---|---|---|
| **E.1 — Autenticación OAuth2** | Obtención del token de acceso a Microsoft 365 vía credenciales de aplicación (service principal). | **~1–2 segundos** | Un único request POST a `login.microsoftonline.com`. No requiere interacción de usuario. |
| **E.2 — Paginación de correos** | Consulta paginada al endpoint `/messages` de Graph API. Filtro por `receivedDateTime` en el rango del slot activo. 10 correos por página. | **~0.5–1 seg/página** + 0.5 seg de pausa entre páginas | Aplica filtro: `receivedDateTime ge {inicio} and receivedDateTime le {fin}`. Se itera hasta agotar páginas. |
| **E.3 — Deduplicación por message_id** | Cada `message_id` se compara contra `procesados.json`. Si ya existe, el correo se omite completamente. | **<10 ms por correo** | Operación en memoria. En correos ya procesados el ahorro es total: se omite descarga, extracción y clasificación. |
| **E.4 — Descarga de adjuntos ZIP** | Para cada correo nuevo con adjuntos `.zip`, se descarga el binario en streaming. Chunk de 64 KB, timeout máximo de 90 segundos. | **~3–60 seg/ZIP** según tamaño (típico 50–500 KB) | Si supera 90 seg → el ZIP NO se marca como procesado → se reintenta en el próximo slot. |
| **E.5 — Almacenamiento en disco** | El ZIP descargado se guarda en `historico_2026/{año}/{mes}/semana_XX/{nombre}.zip`. La estructura es automática según `receivedDateTime`. | **<1 segundo** | Directorios creados automáticamente. Estructura: `historico_2026/2026/01_january/semana_02/`. |
| **E.6 — Extracción inmediata del ZIP** | El ZIP se descomprime al instante en `extraidos/{año}/{mes}/semana_XX/{nombre_zip}/`. | **<2 segundos/ZIP** | Extracción completa del contenido: PDF + XML + archivos de acompañamiento. La carpeta `extraidos/` es la fuente para el portal de descarga. |
| **E.7 — Persistencia del estado** | El `message_id` y los metadatos del correo (fecha, asunto, remitente, adjuntos) se graban en `procesados.json`. | **<100 ms** | Escritura atómica al disco. Si el proceso falla antes de este paso, el correo se reintentará en el próximo slot. |

#### Métricas de volumen esperadas por slot

| Indicador | Valor estimado |
|---|---|
| Correos por slot (día normal) | 5–30 correos |
| ZIPs por correo | 1–3 adjuntos |
| Tamaño promedio por ZIP | 50–500 KB |
| Tiempo total de Fase E (slot típico) | **2–15 minutos** |
| Tiempo total de Fase E (slot con backlog) | **hasta 45 minutos** |

#### Estructura de salida de la Fase E

```
/data/factia/
├── procesados.json                          ← Registro de correos procesados (message_id → metadatos)
├── historico_2026/
│   └── 2026/
│       └── 01_january/
│           └── semana_02/
│               ├── FACTURA_PROVEEDOR_001.zip   ← ZIP original del correo (auditoría)
│               └── FACTURA_PROVEEDOR_002.zip
└── extraidos/
    └── 2026/
        └── 01_january/
            └── semana_02/
                ├── FACTURA_PROVEEDOR_001/      ← Contenido descomprimido
                │   ├── factura.xml
                │   ├── factura.pdf
                │   └── representacion_grafica.pdf
                └── FACTURA_PROVEEDOR_002/
                    └── ...
```

---

### FASE T — Transformación

**Responsable:** `transformacion_service/`
**Disparador:** Inmediatamente después de la Fase E en cada slot del cron, o ejecución manual.

La Transformación se divide en dos etapas secuenciales:

#### Etapa T.1 — Clasificación Documental (`classifier.py` + `validator.py`)

| Sub-fase | Descripción | Tiempo estimado | Notas |
|---|---|---|---|
| **T.1.1 — Escaneo de ZIPs** | Recorre recursivamente `historico_2026/` buscando todos los archivos `.zip`. | **<1 segundo** para cientos de archivos | Operación de sistema de archivos puro. |
| **T.1.2 — Lectura de XMLs internos** | Abre cada ZIP en memoria y localiza todos los archivos `.xml` sin extraerlos a disco. | **~50–200 ms/ZIP** | No escribe en disco. Lee el ZIP directamente en memoria. |
| **T.1.3 — Detección de tipo documental** | Parsea el XML y extrae la etiqueta raíz (sin namespace). Detecta: Invoice, CreditNote, DebitNote, ApplicationResponse, AttachedDocument, Unknown, InvalidXML, SinXML. | **~10–50 ms/XML** | Para `AttachedDocument`: inspecciona el CDATA interno para encontrar el tipo real embebido. |
| **T.1.4 — Aplicación de prioridad** | Si un ZIP tiene múltiples XMLs con tipos distintos, aplica prioridad: Invoice > CreditNote > DebitNote > ApplicationResponse > AttachedDocument > Unknown. | **<1 ms** | Decisión en memoria sobre lista de tipos detectados. |
| **T.1.5 — Extracción a carpeta clasificada** | Extrae el contenido del ZIP a: `curado_2026/facturas/` (si es Invoice) o `rechazados_2026/{Tipo}/` (cualquier otro). | **<2 segundos/ZIP** | Segunda extracción a disco (la primera fue en E.6 a `extraidos/`). Preserva la estructura de ruta original. |

**Tipos documentales y su destino:**

| Tipo detectado | Carpeta destino | Avanza a T.2 |
|---|---|---|
| `Invoice` | `curado_2026/facturas/` | ✅ Sí |
| `CreditNote` | `rechazados_2026/CreditNote/` | ❌ No |
| `DebitNote` | `rechazados_2026/DebitNote/` | ❌ No |
| `ApplicationResponse` | `rechazados_2026/ApplicationResponse/` | ❌ No |
| `AttachedDocument` | `rechazados_2026/AttachedDocument/` o reclasificado | Depende |
| `Unknown` | `rechazados_2026/Unknown/` | ❌ No |
| `SinXML` | `rechazados_2026/SinXML/` | ❌ No |
| `InvalidXML` | `rechazados_2026/InvalidXML/` | ❌ No |

#### Etapa T.2 — Extracción de Metadatos (`metadata_extractor.py`)

Solo los documentos clasificados como **Invoice** entran a esta etapa.

| Sub-fase | Descripción | Tiempo estimado | Notas |
|---|---|---|---|
| **T.2.1 — Escaneo de XMLs curados** | Recorre recursivamente `curado_2026/facturas/` buscando archivos `.xml`. | **<1 segundo** | Operación de sistema de archivos. |
| **T.2.2 — Parseo XML (XPath/UBL 2.1)** | Carga el XML con `ElementTree`, resuelve el nodo raíz Invoice (con manejo especial de `AttachedDocument` con CDATA embebido). | **~20–100 ms/XML** | Para CDATA: localiza el elemento con texto `<Invoice`, extrae el string y lo re-parsea como XML independiente. |
| **T.2.3 — Extracción de campos** | Extrae 9 campos mediante XPath con namespaces UBL: NIT proveedor, número factura, código prefijo, valor sin IVA, IVA total, archivo. | **~5–30 ms/XML** | IVA: suma de todos los `cac:TaxTotal/cbc:TaxAmount` a nivel raíz (evita duplicación de líneas). |
| **T.2.4 — Resolución de fechas** | `fecha_emision`: lookup del nombre del ZIP en `procesados.json` → `receivedDateTime` → parte de fecha. `fecha_vencimiento`: último día calendario del mes de emisión. | **<5 ms/XML** | La fecha no viene del XML sino del correo electrónico, garantizando la fecha real de radicación institucional. |
| **T.2.5 — Escritura de resultados** | Los metadatos se acumulan en `results[]` (memoria) y se persisten en: `facturas_metadata.json` (JSON completo) y `metadata_facturas_2026.csv` (CSV append). | **<100 ms** para el lote completo | Escritura única al finalizar el lote, no por cada factura. |

**Campos extraídos por factura:**

| Campo | Fuente XPath | Descripción |
|---|---|---|
| `proveedor_nit` | `//cac:AccountingSupplierParty//cbc:CompanyID` | NIT del emisor de la factura |
| `numero_factura_original` | `//cbc:ID` | Número completo (ej: `BOGO19018`) |
| `numero_factura` | `re.sub(r"\D", "", original)` | Solo dígitos (ej: `19018`) |
| `codigo` | `re.sub(r"\d", "", original)` | Solo letras (ej: `BOGO`), default `FACT` |
| `valor_factura` | `//cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount` | Subtotal sin IVA. Fallback: `LineExtensionAmount` |
| `iva_facturado_proveedor` | `sum(cac:TaxTotal/cbc:TaxAmount)` | IVA total (raíz únicamente, no líneas) |
| `fecha_emision` | `procesados.json[zip_filename].receivedDateTime` | Fecha de recepción del correo |
| `fecha_vencimiento` | `calendar.monthrange(año, mes)[-1]` | Último día del mes de emisión |
| `observaciones` | Template fijo | `"Factura {numero_factura} radicado ***"` |

---

### Sincronización Post-ETL

Después de cada ejecución de cron (Fase E + Fase T), el sistema realiza una sincronización automática con el portal de Finagro:

| Paso | Descripción | Tiempo estimado |
|---|---|---|
| **S.1 — POST al backend Django** | Envía los resultados del cron (facturas procesadas, errores) al endpoint `POST /api/facturacion/sincronizar-cron/` con token de autenticación `X-Cron-Token`. | **~1–5 segundos** |
| **S.2 — Registro en cron_log.json** | Persiste el resultado del slot (timestamp, estado, mensajes procesados, facturas guardadas, errores, rango de fechas) en `cron_log.json`. Mantiene los últimos 50 registros. | **<100 ms** |

---

## Indicadores Operativos del Sistema

### Conteos en base de datos

| Indicador | Ubicación | Descripción |
|---|---|---|
| **Total de correos procesados** | `procesados.json` (número de claves `message_id`) | Correos únicos descargados desde el inicio del sistema |
| **Total de ZIPs descargados** | `procesados.json` → suma de `attachments[]` por mensaje | Archivos comprimidos recibidos de proveedores |
| **Total de facturas curadas** | `curado_2026/facturas/` (archivos XML) | Facturas UBL válidas clasificadas |
| **Total de documentos rechazados** | `rechazados_2026/` (archivos por tipo) | Notas crédito, débito, respuestas DIAN, inválidos |
| **Total de metadatos extraídos** | `facturas_metadata.json` (longitud del arreglo) | Facturas con todos los campos disponibles para el portal |
| **Ejecuciones de cron registradas** | `cron_log.json` (últimas 50) | Historial de ejecuciones automáticas |

### Distribución temporal del pipeline

```
06:00 AM (Bogotá) ─── Slot 1: correos de 4 PM anterior → 6 AM hoy
11:00 AM (Bogotá) ─── Slot 2: correos de 6 AM → 11 AM hoy
04:00 PM (Bogotá) ─── Slot 3: correos de 11 AM → 4 PM hoy
```

Cobertura diaria: **12 horas de horario laboral** segmentadas en tres ventanas sin solapamiento.

---

## Resiliencia y Manejo de Errores

| Escenario | Comportamiento del sistema |
|---|---|
| **Correo ya procesado** | Se omite completamente (deduplicación por `message_id`). Sin impacto en rendimiento. |
| **Error 401 (token expirado)** | Renueva automáticamente el token OAuth2 y reintenta la request. |
| **Error 429 (rate limit de Graph API)** | Espera el tiempo indicado en el header `Retry-After` y reintenta con backoff exponencial. |
| **Error 5xx (servidor Microsoft)** | Backoff exponencial: 2, 4, 8 segundos. Máximo 3 intentos. |
| **Timeout de descarga (>90s)** | El ZIP **no** se marca como procesado → se reintenta en el próximo slot automáticamente. |
| **ZIP corrupto (BadZipFile)** | Registrado en log, omitido, el proceso continúa con el siguiente archivo. |
| **XML malformado** | Clasificado como `InvalidXML`, movido a `rechazados_2026/InvalidXML/`. |
| **XML sin tipo reconocido** | Clasificado como `Unknown`, movido a `rechazados_2026/Unknown/`. |
| **Fallo en extracción de metadatos** | Error registrado en log, factura omitida, el lote continúa. |
| **Proceso abortado manualmente** | El estado se persiste hasta el último correo exitoso. El próximo slot retoma desde donde se detuvo. |

---

## Glosario Técnico

| Término | Definición en el contexto de FactIA |
|---|---|
| **ETL** | Extract, Transform, Load. Pipeline de datos: Extracción (descarga de correos), Transformación (clasificación + metadatos), Load (sincronización al portal). |
| **Fase E** | Extracción: descarga de ZIPs desde Microsoft 365 vía Graph API. |
| **Fase T** | Transformación: clasificación documental y extracción de campos UBL. |
| **UBL 2.1** | Universal Business Language. Estándar XML adoptado por Colombia para factura electrónica (DIAN). |
| **message_id** | Identificador único de Microsoft 365 para cada correo. Es la clave de deduplicación del sistema. |
| **Graph API** | API de Microsoft para acceder programáticamente a correos de Microsoft 365. |
| **OAuth2 / Service Principal** | Autenticación de máquina a máquina (sin usuario humano) usando credenciales de aplicación registrada en Azure. |
| **ZIP** | Archivo comprimido que contiene los documentos de una factura electrónica (XML + PDF + adjuntos). |
| **XPath** | Lenguaje de consulta para extraer nodos de documentos XML. Usado para leer campos UBL. |
| **curado** | Facturas clasificadas y validadas como Invoice UBL. Listas para extracción de metadatos. |
| **rechazado** | Documento que no corresponde a una factura válida: notas, respuestas DIAN, inválidos. Conservados para auditoría. |
| **procesados.json** | Registro persistente de todos los correos descargados. Es la memoria del sistema entre ejecuciones. |
| **SSE (Server-Sent Events)** | Tecnología web que permite transmitir el log del proceso en tiempo real al portal. |
| **Cron** | Tarea programada que ejecuta el pipeline automáticamente a horas definidas. |
| **Slot** | Ventana de tiempo de un ciclo de cron (06:00, 11:00 o 16:00). |
| **DIAN** | Dirección de Impuestos y Aduanas Nacionales. Entidad que regula la factura electrónica en Colombia. |
| **NIT** | Número de Identificación Tributaria. Identifica al proveedor emisor de la factura. |
| **IVA** | Impuesto al Valor Agregado. Calculado como suma de `TaxTotal/TaxAmount` en el XML. |
