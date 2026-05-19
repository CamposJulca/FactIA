# FactIA - Documentacion Funcional

## 1. Proposito

FactIA automatiza la gestion de facturas electronicas recibidas por Finagro en el buzon `facturacion@finagro.com.co`. El modulo descarga correos, identifica adjuntos ZIP, clasifica documentos DIAN, extrae metadatos desde XML UBL y publica la informacion en el portal corporativo para consulta, auditoria y descarga de soportes.

El objetivo funcional es reducir la operacion manual de descarga, descompresion, lectura y registro de facturas, conservando trazabilidad desde el correo original hasta el registro consolidado.

## 2. Alcance funcional

| Capacidad | Descripcion |
|---|---|
| Descarga de correos | Consulta Microsoft 365 mediante Graph API y descarga adjuntos ZIP del buzon de facturacion. |
| Deduplicacion | Evita reprocesar correos ya descargados usando el `message_id` de Microsoft Graph. |
| Extraccion de ZIPs | Guarda el ZIP original y extrae su contenido para consulta documental. |
| Clasificacion documental | Identifica facturas, notas credito, notas debito, respuestas DIAN, documentos sin XML, XML invalidos y documentos desconocidos. |
| Extraccion de metadatos | Lee datos clave de documentos UBL: proveedor, numero, codigo, valor, IVA y fechas. |
| Consulta en portal | Expone facturas procesadas, estadisticas, semanas disponibles, logs de ejecucion y descargas. |
| Ejecucion manual | Permite descargar y procesar desde la interfaz web con progreso en tiempo real. |
| Ejecucion automatica | Ejecuta el pipeline tres veces al dia: 06:00, 11:00 y 16:00 hora Bogota. |
| Distribucion de soportes | Permite descargar todos los documentos extraidos o paquetes de PDFs por semana. |
| Sincronizacion local | Entrega script/instalador para que usuarios Windows descarguen PDFs por semana. |
| Integracion Mercurio | Incluye flujo adicional para autenticacion robotica, sincronizacion y descarga de PDFs desde Mercurio. |

## 3. Actores

| Actor | Responsabilidad |
|---|---|
| Analista de facturacion | Consulta facturas, ejecuta descargas/procesos manuales y descarga soportes. |
| Sistema FactIA | Descarga, clasifica, extrae metadatos y conserva trazabilidad documental. |
| Scheduler interno | Ejecuta automaticamente los ciclos ETL diarios. |
| Portal Automation Hub | Autentica usuarios, muestra resultados y persiste facturas en base de datos. |
| Microsoft 365 | Fuente de correos y adjuntos del buzon de facturacion. |
| Mercurio | Fuente secundaria de documentos PDF del flujo de trabajo interno. |

## 4. Flujo principal

1. El usuario o el cron inicia una descarga.
2. FactIA obtiene un token OAuth2 de Microsoft.
3. FactIA consulta mensajes del buzon por rango de fechas.
4. Cada correo nuevo se evalua contra `procesados.json`.
5. Los adjuntos `.zip` se descargan a `historico_2026/`.
6. Los ZIPs se extraen a `extraidos/`.
7. El proceso de transformacion clasifica los ZIPs segun el XML contenido.
8. Las facturas y notas credito procesables se leen para extraer metadatos.
9. Los resultados se escriben en `facturas_metadata.json` y CSV.
10. El portal Django sincroniza los resultados a la tabla `FacturaElectronica`.
11. El usuario consulta facturas, estadisticas, semanas y descargas.

## 5. Reglas de negocio

| Codigo | Regla |
|---|---|
| RN-01 | Un correo ya registrado en `procesados.json` no se vuelve a descargar. |
| RN-02 | Solo se descargan adjuntos con extension `.zip`. |
| RN-03 | Si un correo falla antes de guardarse en `procesados.json`, queda disponible para reintento. |
| RN-04 | Si un ZIP contiene varios XML, la clasificacion prioriza `Invoice`, luego `CreditNote`, `DebitNote`, `ApplicationResponse`, `AttachedDocument` y finalmente `Unknown`. |
| RN-05 | Las facturas se almacenan en `curado_2026/facturas/`; los demas tipos se conservan en `rechazados_2026/{tipo}/`. |
| RN-06 | Para la fecha de emision se prioriza la fecha de recepcion del correo; si no se puede correlacionar, se usa `cbc:IssueDate` del XML. |
| RN-07 | La fecha de vencimiento se calcula como el ultimo dia calendario del mes de emision. |
| RN-08 | La unicidad en la base del portal se define por `tipo_documento`, `proveedor_nit` y `numero_factura`. |
| RN-09 | Las descargas por semana empaquetan PDFs desde `extraidos/` y pueden renombrarlos con fecha, NIT y numero de factura si existe metadata. |
| RN-10 | La sincronizacion automatica con Django usa `X-Cron-Token` y no depende de un usuario final autenticado. |

## 6. Tipos documentales

| Tipo tecnico | Significado funcional | Destino |
|---|---|---|
| `Invoice` | Factura electronica de venta | `curado_2026/facturas/` |
| `CreditNote` | Nota credito | `rechazados_2026/CreditNote/` y se incluye en metadata si contiene XML valido |
| `DebitNote` | Nota debito | `rechazados_2026/DebitNote/` |
| `ApplicationResponse` | Respuesta/acuso DIAN | `rechazados_2026/ApplicationResponse/` |
| `AttachedDocument` | Contenedor UBL con documento embebido | Reclasificado si contiene `Invoice`, `CreditNote` o `DebitNote`; de lo contrario `rechazados_2026/AttachedDocument/` |
| `SinXML` | ZIP sin XML | `rechazados_2026/SinXML/` |
| `InvalidXML` | XML malformado o ZIP corrupto al clasificar | `rechazados_2026/InvalidXML/` |
| `Unknown` | Documento no identificado | `rechazados_2026/Unknown/` |

## 7. Datos visibles al usuario

| Campo | Descripcion |
|---|---|
| Tipo documento | Factura, nota credito, nota debito, sin XML o desconocido. |
| NIT proveedor | Identificacion del emisor del documento. |
| Codigo | Parte alfabetica del numero original; si no existe se usa `FACT`. |
| Numero factura | Numero del documento sin caracteres no numericos. |
| Valor factura | Subtotal antes de IVA, tomado de `TaxExclusiveAmount` o `LineExtensionAmount`. |
| IVA facturado proveedor | Suma de `TaxTotal/TaxAmount` a nivel raiz. |
| Fecha emision | Fecha de recepcion del correo o fecha `IssueDate` como respaldo. |
| Fecha vencimiento | Ultimo dia del mes de emision. |
| Observaciones | Texto de radicacion generado por FactIA. |
| Archivo | Ruta del XML o PDF origen en el volumen de datos. |

## 8. Funcionalidades del portal

| Funcion | Descripcion |
|---|---|
| Descargar historico | Ejecuta descarga manual por rango de fechas opcional. |
| Procesar facturas | Clasifica ZIPs y extrae metadatos. |
| Progreso en tiempo real | Muestra logs mediante SSE durante descarga/procesamiento. |
| Abortar operacion | Solicita cancelacion segura del proceso activo. |
| Listar facturas | Muestra facturas persistidas en base de datos. |
| Estadisticas | Resume mensajes, correos con ZIP, total ZIPs y facturas extraidas. |
| Cron log | Consulta las ultimas ejecuciones automaticas. |
| Descargar carpetas | Genera o sirve un ZIP completo con archivos extraidos. |
| Descargar PDFs por semana | Entrega un ZIP con PDFs de una semana especifica. |
| Descargar script/instalador | Entrega utilidades Windows para sincronizacion local. |
| Mercurio | Prueba login, sincroniza documentos y permite descargar PDFs individuales o masivos. |

## 9. Salidas del proceso

| Salida | Uso |
|---|---|
| `historico_2026/` | Conserva ZIPs originales como evidencia. |
| `extraidos/` | Contiene documentos descomprimidos para consulta y descarga. |
| `curado_2026/facturas/` | Contiene documentos clasificados como facturas. |
| `rechazados_2026/` | Conserva documentos no facturables o invalidos para auditoria. |
| `procesados.json` | Memoria de correos descargados y adjuntos asociados. |
| `facturas_metadata.json` | Resultado estructurado del ultimo procesamiento. |
| `metadata_facturas_2026.csv` | Exportacion CSV incremental. |
| `cron_log.json` | Historial de ejecuciones automaticas. |

