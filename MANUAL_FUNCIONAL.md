# FactIA — Manual Funcional
## Módulo de Facturación Electrónica · Finagro

---

## ¿Qué hace este módulo?

FactIA automatiza la gestión de facturas electrónicas que llegan al buzón de correo **facturacion@finagro.com.co**. El módulo realiza dos tareas principales:

1. **Descarga** los correos y sus archivos adjuntos directamente desde Microsoft 365.
2. **Procesa** esos archivos para extraer la información relevante de cada factura (proveedor, valor, IVA, fechas, etc.).

El resultado final es un listado consolidado de todas las facturas recibidas, disponible para consulta desde el portal.

---

## ¿Cómo funciona paso a paso?

### Paso 1 — Descarga de correos

El módulo se conecta al buzón de correo de facturación usando credenciales de Microsoft. Revisa todos los mensajes dentro del rango de fechas indicado y descarga únicamente los archivos adjuntos comprimidos (ZIP) que contienen las facturas electrónicas.

- Los correos ya descargados en sesiones anteriores **no se vuelven a descargar** (el sistema recuerda lo que ya procesó).
- El progreso se puede ver en tiempo real desde el portal.

### Paso 2 — Clasificación de documentos

Una vez descargados los archivos ZIP, el sistema los abre y revisa qué tipo de documento contienen:

| Tipo de documento | Qué es |
|---|---|
| **Factura** | Documento de cobro de un proveedor a Finagro |
| **Nota crédito** | Documento que corrige o anula parcialmente una factura |
| **Nota débito** | Documento que ajusta el valor de una factura al alza |
| **Respuesta de aplicación** | Acuse de recibo o respuesta de la DIAN |
| **Otro / Sin XML** | Archivo no reconocido o sin contenido válido |

Solo las **facturas** pasan a la siguiente etapa. Los demás documentos quedan registrados como rechazados para auditoría.

### Paso 3 — Extracción de información

De cada factura válida, el sistema extrae automáticamente los siguientes datos:

| Campo | Descripción |
|---|---|
| **NIT del proveedor** | Identificación tributaria de quien factura |
| **Número de factura** | Número único del documento |
| **Código** | Prefijo alfanumérico de la factura (ej: BOGO, FE) |
| **Valor factura** | Subtotal sin IVA |
| **IVA facturado** | Valor del impuesto discriminado en la factura |
| **Fecha de emisión** | Fecha en que se recibió el correo con la factura |
| **Fecha de vencimiento** | Último día del mes de emisión |
| **Observaciones** | Nota de radicado interno |

---

## ¿Qué puede hacer el usuario desde el portal?

### Descargar facturas
Permite seleccionar un rango de fechas y lanzar la descarga de correos desde Microsoft 365. El progreso se muestra en pantalla con mensajes en tiempo real. Si es necesario, se puede cancelar la operación en cualquier momento.

### Procesar facturas
Una vez descargados los archivos, este botón inicia la clasificación y extracción de datos. Al finalizar, el portal muestra cuántas facturas fueron procesadas y cuántos archivos fueron rechazados.

### Ver listado de facturas
Muestra la tabla completa de facturas procesadas con todos sus campos. Se puede filtrar por mes para revisar períodos específicos.

### Ver estadísticas
Resumen mensual que indica cuántos correos llegaron, cuántos tenían adjuntos ZIP y cuántos ZIPs se procesaron exitosamente.

### Cancelar operación
Disponible durante una descarga o procesamiento activo. Detiene el proceso de forma segura sin perder el trabajo ya realizado.

---

## ¿De dónde vienen las facturas?

Las facturas son enviadas por los proveedores de Finagro directamente al correo **facturacion@finagro.com.co**. Cada correo puede traer uno o más archivos ZIP, y cada ZIP puede contener uno o varios documentos XML en formato estándar de la DIAN (UBL 2.1).

El módulo solo procesa los documentos que corresponden a **facturas de venta** válidas según el estándar electrónico colombiano.

---

## ¿Dónde se guardan los datos?

Los archivos descargados y procesados se almacenan en un volumen de datos persistente del servidor. La información no se borra entre sesiones. La estructura es:

- **Histórico de correos**: archivos ZIP tal como llegaron, organizados por fecha de recepción.
- **Facturas curadas**: documentos XML de facturas válidas, extraídos de los ZIPs.
- **Rechazados**: archivos que no corresponden a facturas válidas, conservados para auditoría.
- **Base de datos de facturas**: registro consolidado con todos los campos extraídos.

---

## Acceso y seguridad

El módulo requiere usuario y contraseña para ingresar desde el portal. Las credenciales de conexión a Microsoft 365 (DIAN) son configuradas por el administrador del sistema y no son visibles para el usuario final.

---

## Glosario

| Término | Significado |
|---|---|
| **ZIP** | Archivo comprimido que contiene uno o varios documentos |
| **XML** | Formato de archivo estructurado usado por la DIAN para facturas electrónicas |
| **UBL** | Estándar internacional de factura electrónica adoptado por Colombia |
| **DIAN** | Dirección de Impuestos y Aduanas Nacionales |
| **Graph API** | Servicio de Microsoft para acceder a correos de Microsoft 365 |
| **NIT** | Número de Identificación Tributaria |
| **IVA** | Impuesto al Valor Agregado |
| **SSE** | Tecnología que permite ver el progreso en tiempo real desde el navegador |
