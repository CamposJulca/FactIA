#!/bin/bash
# =============================================================================
# build.sh — Cross-compila sincronizar_facturas.py a .exe para Windows
#            usando la imagen cdrx/pyinstaller-windows (Wine + Python 3.11)
#
# Requisitos: Docker corriendo en el servidor Linux
# Resultado:  dist/SincronizarFacturas.exe
#
# Uso:
#   cd /home/desarrollo/Finagro/FactIA/descargar_service
#   bash build.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/dist"

echo ""
echo "=========================================="
echo "  Build SincronizarFacturas.exe"
echo "=========================================="
echo "Directorio fuente : $SCRIPT_DIR"
echo "Directorio salida : $OUTPUT_DIR"
echo ""

echo "Descargando imagen Docker de compilacion..."
docker pull cdrx/pyinstaller-windows:python3 --quiet

echo "Compilando para Windows (pyinstaller --onefile --windowed)..."
docker run --rm \
  -v "$SCRIPT_DIR:/src" \
  cdrx/pyinstaller-windows:python3 \
  "pyinstaller --onefile --windowed --name SincronizarFacturas --clean /src/sincronizar_facturas.py"

# El .exe queda en el volumen /src/dist/ dentro del contenedor = $SCRIPT_DIR/dist/
EXE_PATH="$SCRIPT_DIR/dist/SincronizarFacturas.exe"

if [ -f "$EXE_PATH" ]; then
    SIZE=$(du -h "$EXE_PATH" | cut -f1)
    echo ""
    echo "=========================================="
    echo "  BUILD EXITOSO"
    echo "  Archivo: $EXE_PATH"
    echo "  Tamanio: $SIZE"
    echo "=========================================="

    # Copiar al volumen de FactIA via docker cp
    CONTAINER=$(docker ps --filter "name=factia" --format "{{.Names}}" | head -1)
    if [ -n "$CONTAINER" ]; then
        docker cp "$EXE_PATH" "$CONTAINER:/data/factia/SincronizarFacturas.exe"
        echo "  Copiado al contenedor: $CONTAINER:/data/factia/SincronizarFacturas.exe"
    else
        echo "  Contenedor factia no encontrado — copia manual requerida"
    fi
else
    echo ""
    echo "ERROR: No se genero el .exe"
    echo "Revisa los logs de compilacion arriba."
    exit 1
fi
