#!/usr/bin/env python3
"""
inspeccionar_correo.py - Diagnostico read-only del buzon FactIA via Graph.

Reusa historico_service/auth.py y graph_client.py para no duplicar logica de
token, reintentos y refresh-on-401. NO modifica procesados.json ni el pipeline.

Pensado para correr DENTRO del contenedor automation-hub-finagro-factia-1
(WORKDIR /app), donde las env vars TENANT_ID/CLIENT_ID/CLIENT_SECRET estan
disponibles.

Uso:
    python /app/herramientas_diagnostico/inspeccionar_correo.py \
        --from cepino@finagro.com.co \
        --fecha 2026-05-21 \
        --asunto-contiene "cuenta de cobro"
"""
import argparse
import mimetypes
import os
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

# Permite importar el paquete historico_service. En el contenedor WORKDIR es
# /app, asi que /app/herramientas_diagnostico/ tiene a /app como padre.
_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_ROOT = os.path.dirname(_HERE)
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from historico_service.auth import get_access_token         # noqa: E402
from historico_service.config import MAILBOX                # noqa: E402
from historico_service.graph_client import GraphClient      # noqa: E402

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SELECT_MSG = "id,subject,receivedDateTime,from,hasAttachments,internetMessageId"
SELECT_ATT = "id,name,contentType,size,isInline"

PERMISO_MSG = (
    "Permisos Graph insuficientes - verificar Mail.Read Application en Azure"
)


def _abort_permisos(contexto, status):
    print(f"ERROR Graph {status} en {contexto}: {PERMISO_MSG}", file=sys.stderr)
    sys.exit(2)


def _safe_segment(s):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)


def listar_correos(gc, sender, fecha, asunto_contiene):
    # Solo filtramos por sender en el lado Graph. El rango de fecha se aplica
    # client-side porque combinar from/emailAddress/address eq con
    # receivedDateTime ge/le + orderby dispara "InefficientFilter" en Graph.
    filtro = f"from/emailAddress/address eq '{sender}'"
    encoded_filter = quote(filtro, safe="'")
    url = (
        f"{GRAPH_BASE}/users/{MAILBOX}/messages"
        f"?$filter={encoded_filter}"
        f"&$top=50"
        f"&$select={SELECT_MSG}"
    )

    todos = []
    while url:
        resp = gc._request("GET", url)
        if resp.status_code in (401, 403):
            _abort_permisos("list messages", resp.status_code)
        if resp.status_code != 200:
            print(
                f"ERROR Graph {resp.status_code} listando mensajes: "
                f"{resp.text[:300]}",
                file=sys.stderr,
            )
            sys.exit(3)
        body = resp.json()
        todos.extend(body.get("value", []))
        url = body.get("@odata.nextLink")

    # Sin $orderby server-side (dispara InefficientFilter); ordenamos client-side.
    todos.sort(key=lambda m: m.get("receivedDateTime") or "")

    print(f"Correos totales del remitente (todas las fechas): {len(todos)}")

    # Filtro de fecha client-side. receivedDateTime de Graph viene en UTC
    # (sufijo 'Z'). El rango [fecha 00:00:00, fecha 23:59:59] se interpreta
    # tambien en UTC: un correo recibido en Bogota (UTC-5) a las 7 PM aparece
    # como las 00:00 UTC del dia siguiente y NO entrara en este rango.
    inicio = datetime.fromisoformat(f"{fecha}T00:00:00").replace(tzinfo=timezone.utc)
    fin = datetime.fromisoformat(f"{fecha}T23:59:59").replace(tzinfo=timezone.utc)
    en_fecha = []
    for msg in todos:
        rdt = msg.get("receivedDateTime")
        if not rdt:
            continue
        try:
            dt = datetime.fromisoformat(rdt.replace("Z", "+00:00"))
        except ValueError:
            continue
        if inicio <= dt <= fin:
            en_fecha.append(msg)

    print(f"Correos en la fecha {fecha} UTC: {len(en_fecha)}")

    # Filtro de asunto client-side al final.
    if asunto_contiene:
        needle = asunto_contiene.lower()
        en_fecha = [
            m for m in en_fecha
            if needle in (m.get("subject") or "").lower()
        ]
    return en_fecha


def listar_adjuntos(gc, message_id):
    url = (
        f"{GRAPH_BASE}/users/{MAILBOX}"
        f"/messages/{message_id}/attachments?$select={SELECT_ATT}"
    )
    resp = gc._request("GET", url)
    if resp.status_code in (401, 403):
        _abort_permisos(f"list attachments {message_id}", resp.status_code)
    if resp.status_code != 200:
        print(
            f"  WARN HTTP {resp.status_code} listando adjuntos "
            f"({resp.text[:200]})",
            file=sys.stderr,
        )
        return []
    return resp.json().get("value", [])


def procesar_correo(gc, msg, idx, out_root):
    subject = msg.get("subject", "")
    msg_id = msg["id"]
    from_addr = (msg.get("from") or {}).get("emailAddress") or {}
    received = msg.get("receivedDateTime", "")

    print(f"\n[{idx}] {subject!r}")
    print(f"    from      : {from_addr.get('address')}  ({from_addr.get('name')})")
    print(f"    received  : {received}")
    print(f"    msgId     : {msg_id}")
    print(f"    inetMsgId : {msg.get('internetMessageId')}")
    print(f"    hasAtt    : {msg.get('hasAttachments')}")

    out_dir = os.path.join(out_root, str(idx))
    os.makedirs(out_dir, exist_ok=True)

    adjuntos = listar_adjuntos(gc, msg_id)
    print(f"    adjuntos  : {len(adjuntos)}")
    zips_descargados = []
    for att in adjuntos:
        name = att.get("name") or "(sin_nombre)"
        size = att.get("size", 0)
        ctype = att.get("contentType", "")
        inline = att.get("isInline", False)
        print(f"      - {name}  [{ctype}, {size} B, inline={inline}]")

        dest = os.path.join(out_dir, name)
        try:
            gc.download_attachment(msg_id, att["id"], dest)
        except Exception as exc:
            print(f"        ERROR descargando '{name}': {exc}", file=sys.stderr)
            continue

        if name.lower().endswith(".zip"):
            zips_descargados.append(dest)

    zip_entries_total = 0
    for zpath in zips_descargados:
        unzipped_dir = os.path.join(
            out_dir, "unzipped", os.path.basename(zpath)
        )
        os.makedirs(unzipped_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(unzipped_dir)
                entries = zf.namelist()
        except zipfile.BadZipFile as exc:
            print(
                f"      ZIP invalido ({os.path.basename(zpath)}): {exc}",
                file=sys.stderr,
            )
            continue
        zip_entries_total += len(entries)
        print(f"      ZIP {os.path.basename(zpath)} -> {len(entries)} entrada(s):")
        for entry in entries:
            mime, _ = mimetypes.guess_type(entry)
            print(f"         . {entry}  [{mime or 'desconocido'}]")

    return {
        "adjuntos": len(adjuntos),
        "zips": len(zips_descargados),
        "zip_entries": zip_entries_total,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Inspecciona correos de un remitente/fecha en el buzon FactIA "
            "(read-only)."
        ),
    )
    parser.add_argument(
        "--from", dest="sender", required=True,
        help="Email del remitente (from/emailAddress/address en Graph).",
    )
    parser.add_argument(
        "--fecha", required=True,
        help="Fecha de recepcion YYYY-MM-DD (rango 00:00:00Z - 23:59:59Z UTC).",
    )
    parser.add_argument(
        "--asunto-contiene", default=None,
        help="Substring opcional a buscar en el subject (case-insensitive).",
    )
    parser.add_argument(
        "--output", default=None,
        help="Directorio de descarga (default: /tmp/diagnostico/{from}_{fecha}).",
    )
    args = parser.parse_args()

    if (
        len(args.fecha) != 10
        or args.fecha[4] != "-"
        or args.fecha[7] != "-"
        or not args.fecha.replace("-", "").isdigit()
    ):
        print("ERROR: --fecha debe tener formato YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    out_root = args.output or os.path.join(
        "/tmp/diagnostico",
        f"{_safe_segment(args.sender)}_{args.fecha}",
    )
    os.makedirs(out_root, exist_ok=True)

    print("=" * 70)
    print(f"Buzon          : {MAILBOX}")
    print(f"Remitente      : {args.sender}")
    print(f"Fecha          : {args.fecha}")
    print(f"Asunto filtro  : {args.asunto_contiene!r}")
    print(f"Output         : {out_root}")
    print("=" * 70)
    fecha_siguiente = (
        date.fromisoformat(args.fecha) + timedelta(days=1)
    ).isoformat()
    print(
        f"Nota: fecha se interpreta en UTC. Bogota UTC-5; correos del "
        f"{args.fecha} 19:00-23:59 Bogota apareceran como {fecha_siguiente} UTC."
    )

    try:
        token = get_access_token()
    except Exception as exc:
        texto = str(exc).lower()
        if any(t in texto for t in ("401", "403", "unauthorized", "forbidden")):
            print(
                f"ERROR obteniendo token: {PERMISO_MSG} ({exc})",
                file=sys.stderr,
            )
        else:
            print(f"ERROR obteniendo token Graph: {exc}", file=sys.stderr)
        sys.exit(2)

    gc = GraphClient(token, refresh_token_fn=get_access_token)

    correos = listar_correos(gc, args.sender, args.fecha, args.asunto_contiene)
    print(f"\nCorreos encontrados: {len(correos)}")
    if not correos:
        print("(Cero correos coinciden con el filtro - caso normal, sin error)")
        sys.exit(0)

    total_att = 0
    total_zip = 0
    total_zip_entries = 0
    for i, msg in enumerate(correos, 1):
        stats = procesar_correo(gc, msg, i, out_root)
        total_att += stats["adjuntos"]
        total_zip += stats["zips"]
        total_zip_entries += stats["zip_entries"]

    print("\n" + "=" * 70)
    print("RESUMEN")
    print("=" * 70)
    print(f"  Correos       : {len(correos)}")
    print(f"  Adjuntos      : {total_att}")
    print(f"  ZIPs          : {total_zip}")
    print(f"  Entradas ZIP  : {total_zip_entries}")
    print(f"  Output        : {out_root}")


if __name__ == "__main__":
    main()
