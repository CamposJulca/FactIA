# FactIA - Arquitectura de Software

## 1. Vista general

FactIA esta disenado como un servicio ETL documental desacoplado del portal principal. El servicio Flask ejecuta la integracion con Microsoft 365 y el procesamiento de archivos. El portal Django consume FactIA por HTTP, autentica usuarios, persiste resultados y ofrece la interfaz web React.

```text
┌──────────────────────────────┐
│ Usuario / Analista           │
└──────────────┬───────────────┘
               │ Navegador
               ▼
┌──────────────────────────────┐
│ Frontend React               │
│ FacturacionPage.js           │
└──────────────┬───────────────┘
               │ /api/facturacion/
               ▼
┌──────────────────────────────┐
│ Backend Django + DRF         │
│ modules/facturacion          │
└───────┬──────────────┬───────┘
        │              │
        │ HTTP interno │ ORM
        ▼              ▼
┌──────────────────┐  ┌──────────────────────┐
│ FactIA Flask     │  │ Base de datos portal │
│ :8002            │  │ FacturaElectronica   │
└───────┬──────────┘  └──────────────────────┘
        │
        ├──────────────► Microsoft Graph / Exchange Online
        │
        ▼
┌─────────────────────────────────────────────┐
│ Volumen persistente /data/factia            │
│ historico, extraidos, curado, rechazados,   │
│ procesados.json, facturas_metadata.json     │
└─────────────────────────────────────────────┘
```

## 2. Estilo arquitectonico

| Aspecto | Decision |
|---|---|
| Separacion de responsabilidades | FactIA procesa documentos; Django gestiona usuarios, API publica y persistencia relacional. |
| Comunicacion | HTTP interno entre Django y FactIA. |
| Estado ETL | Persistencia basada en archivos dentro de un volumen Docker. |
| Estado transaccional | Base de datos del portal mediante modelo Django. |
| Ejecucion asincrona ligera | Threads para jobs SSE y APScheduler para cron. |
| Integracion externa | Microsoft Graph con OAuth2; Mercurio mediante automatizacion web. |

## 3. Componentes

### 3.1 Frontend React

Responsabilidades:

- Mostrar tablero de facturacion.
- Iniciar descargas y procesamientos.
- Consumir eventos SSE.
- Listar facturas, estadisticas y cron log.
- Descargar paquetes de documentos.
- Ejecutar flujos de Mercurio.

### 3.2 Backend Django

Responsabilidades:

- Autenticacion de usuarios.
- API publica bajo `/api/facturacion/`.
- Proxy hacia FactIA para procesos largos y descargas.
- Persistencia de facturas en `FacturaElectronica`.
- Registro de ejecuciones en `Execution` y `ExecutionLog`.
- Validacion de token interno para sincronizacion cron.

### 3.3 Servicio FactIA Flask

Responsabilidades:

- Exponer API interna de descarga, procesamiento, consulta y healthcheck.
- Ejecutar jobs manuales con streaming SSE.
- Mantener scheduler automatico.
- Coordinar `historico_service` y `transformacion_service`.
- Administrar archivos persistentes del pipeline.

### 3.4 `historico_service`

Responsabilidades:

- Autenticacion OAuth2.
- Consulta paginada de correos.
- Descarga de adjuntos ZIP.
- Deduplicacion por `message_id`.
- Escritura de `procesados.json`.
- Extraccion inicial a `extraidos/`.

### 3.5 `transformacion_service`

Responsabilidades:

- Clasificacion por tipo documental.
- Extraccion de ZIPs a carpetas curadas o rechazadas.
- Lectura XML UBL con soporte para `AttachedDocument`.
- Generacion de metadatos JSON y CSV.

### 3.6 Volumen de datos

Responsabilidades:

- Evidencia original de correos y ZIPs.
- Soporte de auditoria.
- Estado operativo para reintentos y deduplicacion.
- Archivos de salida consumidos por el portal.

## 4. Flujo ETL

```text
Microsoft 365
    │
    │ 1. OAuth2 + Graph API
    ▼
historico_service
    │
    ├─ Lee mensajes por rango de fechas
    ├─ Omite message_id ya procesados
    ├─ Descarga ZIPs
    ├─ Guarda historico_2026/
    ├─ Extrae extraidos/
    └─ Actualiza procesados.json
    │
    ▼
transformacion_service
    │
    ├─ Escanea historico_2026/
    ├─ Clasifica XMLs por raiz UBL
    ├─ Extrae a curado_2026/ o rechazados_2026/
    ├─ Extrae metadatos
    └─ Escribe facturas_metadata.json
    │
    ▼
Django
    │
    ├─ Lee facturas desde FactIA
    ├─ update_or_create por llave unica
    └─ Publica al frontend
```

## 5. Vista de despliegue

```text
┌──────────────────────────────────────────────────────┐
│ Docker / Servidor                                    │
│                                                      │
│  ┌──────────────────┐     ┌──────────────────────┐  │
│  │ frontend React   │     │ backend Django       │  │
│  │ static/nginx     │────►│ gunicorn :8000       │  │
│  └──────────────────┘     └──────────┬───────────┘  │
│                                      │              │
│                                      ▼              │
│                           ┌──────────────────────┐  │
│                           │ factia Flask         │  │
│                           │ gunicorn :8002       │  │
│                           │ workers=1            │  │
│                           └──────────┬───────────┘  │
│                                      │              │
│                                      ▼              │
│                           ┌──────────────────────┐  │
│                           │ /data/factia volume  │  │
│                           └──────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

Requisitos de despliegue:

- Montar `/data/factia` como volumen persistente.
- Configurar secretos de Microsoft Graph.
- Configurar `BACKEND_URL` desde FactIA hacia Django.
- Configurar `CRON_INTERNAL_TOKEN` igual en FactIA y Django.
- Ejecutar FactIA con un solo worker para no duplicar el scheduler.

## 6. Vista de datos

```text
/data/factia/
├── procesados.json
├── facturas_metadata.json
├── metadata_facturas_2026.csv
├── cron_log.json
├── FacturasElectronicas.zip
├── historico_2026/
│   └── {year}/{month}/semana_{ww}/*.zip
├── extraidos/
│   └── {year}/{month}/semana_{ww}/{zip_name}/...
├── curado_2026/
│   └── facturas/{year}/{month}/semana_{ww}/{zip_name}/...
└── rechazados_2026/
    ├── CreditNote/
    ├── DebitNote/
    ├── ApplicationResponse/
    ├── AttachedDocument/
    ├── SinXML/
    ├── InvalidXML/
    └── Unknown/
```

Modelo relacional del portal:

```text
Automation 1 ── N Execution 1 ── N FacturaElectronica
```

Llave funcional de factura:

```text
tipo_documento + proveedor_nit + numero_factura
```

## 7. Contratos entre servicios

### 7.1 Django a FactIA

| Operacion | Contrato |
|---|---|
| Descargar | `POST {FACTIA_URL}/api/descargar/` con `fecha_desde` y `fecha_hasta` opcionales. |
| Descargar streaming | `POST {FACTIA_URL}/api/descargar/stream/` y reenvio SSE al navegador. |
| Procesar | `POST {FACTIA_URL}/api/procesar/`. |
| Procesar streaming | `POST {FACTIA_URL}/api/procesar/stream/`; Django persiste al recibir `event: result`. |
| Listar facturas | `GET {FACTIA_URL}/api/facturas/`. |
| Stats | `GET {FACTIA_URL}/api/stats/`. |
| Cron log | `GET {FACTIA_URL}/api/cron-log/`. |
| Descargar documentos | Endpoints de ZIP completo, semanas y PDFs. |

### 7.2 FactIA a Django

| Operacion | Contrato |
|---|---|
| Sincronizacion cron | `POST {BACKEND_URL}/api/facturacion/sincronizar-cron/` |
| Seguridad | Header `X-Cron-Token: {CRON_INTERNAL_TOKEN}` |
| Resultado esperado | JSON `{ "total": N }` |

## 8. Seguridad

| Superficie | Control |
|---|---|
| API de portal | Vistas principales usan `IsAuthenticated`. |
| API interna cron | `X-Cron-Token` compartido. |
| Microsoft Graph | OAuth2 con service principal. |
| Secretos | Variables de entorno; no deben versionarse. |
| Archivos | Descargas servidas mediante endpoints controlados. |
| Mercurio PDFs | Validacion de nombre para evitar path traversal en descarga individual. |

Consideraciones:

- Las credenciales de Microsoft y Mercurio deben rotarse y almacenarse fuera del codigo.
- Los endpoints publicos de instalador/script no requieren autenticacion por diseno actual.
- El volumen `/data/factia` contiene informacion sensible y debe tener controles de acceso y backup.

## 9. Disponibilidad y recuperacion

| Escenario | Comportamiento |
|---|---|
| Correo ya procesado | Se omite sin descargar adjuntos. |
| Falla descargando adjunto | El mensaje no se marca como procesado y puede reintentarse. |
| Abort manual | Se guarda el progreso y se detiene el job. |
| XML invalido | Se clasifica como `InvalidXML` y el proceso continua. |
| ZIP sin XML | Se conserva como `SinXML`. |
| Error temporal Graph | Reintentos y backoff. |
| Error sincronizando Django | Se registra en cron log; FactIA conserva metadata local. |

## 10. Decisiones arquitectonicas relevantes

| Decision | Justificacion | Consecuencia |
|---|---|---|
| Servicio Flask separado | Aisla ETL documental del backend principal. | Requiere contrato HTTP y healthcheck. |
| Persistencia local en volumen | Facilita auditoria de archivos originales y reprocesamiento. | Requiere backup y gestion de crecimiento. |
| Scheduler en FactIA | Mantiene el pipeline cerca de los servicios ETL. | Debe ejecutarse con un solo worker. |
| SSE para jobs manuales | Da visibilidad de procesos largos al usuario. | Proxy/Nginx debe permitir streaming y timeouts altos. |
| `update_or_create` en Django | Evita duplicados funcionales. | Reprocesar puede actualizar registros existentes. |
| Clasificacion por XML raiz | Aprovecha el estandar UBL/DIAN. | Documentos no estandar caen en rechazados. |

## 11. Puntos de extension

| Extension | Lugar recomendado |
|---|---|
| Nuevos campos UBL | `transformacion_service/metadata_extractor.py` |
| Nuevos tipos documentales | `transformacion_service/validator.py` y `classifier.py` |
| Nueva persistencia de FactIA | Reemplazar JSON/CSV por repositorio o base dedicada. |
| Nuevas estadisticas | `FactIA/app.py` endpoint `/api/stats/` y vista Django proxy. |
| Mejoras de frontend | `automation-hub-finagro/frontend/src/pages/FacturacionPage.js` |
| Hardening de secretos | Configuracion Docker/entorno y variables de Django/FactIA. |

