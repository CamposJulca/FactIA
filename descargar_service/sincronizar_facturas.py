"""
SincronizarFacturasGUI.py
Interfaz gráfica para sincronizar facturas electrónicas desde el portal Automation Hub.
Descarga todos los PDFs de extraidos/ (facturas + notas crédito + otros documentos).
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import requests
import zipfile
import os
import json
import base64
import tempfile
from datetime import datetime
from pathlib import Path

# ─── Configuración por defecto ────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "BASE_URL":  "https://facturacion-electronica.ngrok.io",
    "USUARIO":   "admin",
    "PASSWORD":  "Finagro2026!",
    "DESTINO":   r"C:\Users\cdcampos\Documents\FacturasElectronicas",
}
STATE_FILE = Path.home() / ".sincronizar_facturas_state.json"

# ─── Directorio de logs (misma carpeta que el script) ─────────────────────────
LOG_DIR = Path(__file__).parent

# ─── Paleta de colores ─────────────────────────────────────────────────────────
BG_DARK    = "#0D1117"
BG_PANEL   = "#161B22"
BG_CARD    = "#1C2128"
ACCENT     = "#2EA043"        # verde GitHub-style
ACCENT_DIM = "#238636"
CYAN       = "#58A6FF"
YELLOW     = "#D29922"
RED        = "#F85149"
TEXT_PRI   = "#E6EDF3"
TEXT_SEC   = "#8B949E"
BORDER     = "#30363D"

# ══════════════════════════════════════════════════════════════════════════════
class SincronizadorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sincronizador de Facturas Electrónicas")
        self.geometry("860x660")
        self.minsize(720, 560)
        self.configure(bg=BG_DARK)
        self.resizable(True, True)

        # Estado
        self.config = dict(DEFAULT_CONFIG)
        self.load_state()
        self._running = False
        self._thread  = None

        # Fuentes
        self.font_title  = ("Consolas", 15, "bold")
        self.font_sub    = ("Consolas", 10)
        self.font_body   = ("Consolas", 10)
        self.font_small  = ("Consolas",  9)
        self.font_log    = ("Courier New", 9)
        self.font_stat   = ("Consolas", 22, "bold")

        self._build_ui()
        self._update_last_sync_label()
        self._init_log_file()   # abrir/crear archivo de log del día

    # ── Persistencia ──────────────────────────────────────────────────────────
    def load_state(self):
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                self.last_sync = data.get("last_sync")
                saved_cfg = data.get("config", {})
                self.config.update(saved_cfg)
            except Exception:
                self.last_sync = None
        else:
            self.last_sync = None

    def save_state(self):
        data = {
            "last_sync": self.last_sync,
            "config": {
                "BASE_URL": self.var_url.get(),
                "USUARIO":  self.var_user.get(),
                "PASSWORD": self.var_pass.get(),
                "DESTINO":  self.var_dest.get(),
            }
        }
        STATE_FILE.write_text(json.dumps(data, indent=2))

    # ── Construcción UI ───────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG_PANEL, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⬡  FACTURAS ELECTRÓNICAS",
                 font=("Consolas", 14, "bold"),
                 fg=CYAN, bg=BG_PANEL).pack(side="left", padx=20)
        self.lbl_clock = tk.Label(hdr, font=self.font_small,
                                  fg=TEXT_SEC, bg=BG_PANEL)
        self.lbl_clock.pack(side="right", padx=20)
        self._tick_clock()

        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.pack(fill="x")

        # ── Cuerpo principal (2 columnas) ─────────────────────────────────────
        body = tk.Frame(self, bg=BG_DARK)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        body.columnconfigure(0, weight=1, minsize=260)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(1, weight=1)

        # ── Panel izquierdo ───────────────────────────────────────────────────
        left = tk.Frame(body, bg=BG_DARK)
        left.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0,10))

        self._build_config_panel(left)
        self._build_stats_panel(left)

        # ── Panel derecho: log ────────────────────────────────────────────────
        right_top = tk.Frame(body, bg=BG_DARK)
        right_top.grid(row=0, column=1, sticky="ew")
        tk.Label(right_top, text="REGISTRO DE ACTIVIDAD",
                 font=("Consolas", 9, "bold"),
                 fg=TEXT_SEC, bg=BG_DARK).pack(anchor="w")

        log_frame = tk.Frame(body, bg=BG_CARD,
                              highlightthickness=1,
                              highlightbackground=BORDER)
        log_frame.grid(row=1, column=1, sticky="nsew", pady=(4,0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_box = scrolledtext.ScrolledText(
            log_frame, bg=BG_CARD, fg=TEXT_SEC,
            font=self.font_log, bd=0,
            insertbackground=TEXT_PRI,
            selectbackground=ACCENT_DIM,
            relief="flat", wrap="word",
            state="disabled",
        )
        self.log_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.log_box.tag_config("ok",   foreground=ACCENT)
        self.log_box.tag_config("err",  foreground=RED)
        self.log_box.tag_config("warn", foreground=YELLOW)
        self.log_box.tag_config("info", foreground=CYAN)
        self.log_box.tag_config("dim",  foreground=TEXT_SEC)

        # ── Barra inferior ────────────────────────────────────────────────────
        bottom = tk.Frame(self, bg=BG_PANEL, pady=10)
        bottom.pack(fill="x", side="bottom")
        tk.Frame(bottom, bg=BORDER, height=1).pack(fill="x")

        btn_frame = tk.Frame(bottom, bg=BG_PANEL)
        btn_frame.pack(pady=(8,0))

        self.btn_sync = tk.Button(
            btn_frame,
            text="  ▶  SINCRONIZAR",
            font=("Consolas", 11, "bold"),
            bg=ACCENT_DIM, fg=TEXT_PRI,
            activebackground=ACCENT,
            activeforeground=TEXT_PRI,
            bd=0, padx=28, pady=10,
            cursor="hand2",
            command=self._start_sync,
            relief="flat",
        )
        self.btn_sync.pack(side="left", padx=8)

        self.btn_recuperar = tk.Button(
            btn_frame,
            text="  ⬇  RECUPERAR FALTANTES",
            font=("Consolas", 11, "bold"),
            bg="#2D1B00", fg=YELLOW,
            activebackground="#4A2E00",
            activeforeground=YELLOW,
            bd=0, padx=18, pady=10,
            cursor="hand2",
            command=self._start_recuperar,
            relief="flat",
        )
        self.btn_recuperar.pack(side="left", padx=4)

        self.btn_stop = tk.Button(
            btn_frame,
            text="  ■  DETENER",
            font=("Consolas", 11, "bold"),
            bg=BG_CARD, fg=RED,
            activebackground=RED,
            activeforeground=TEXT_PRI,
            bd=0, padx=20, pady=10,
            cursor="hand2",
            command=self._stop_sync,
            relief="flat",
            state="disabled",
        )
        self.btn_stop.pack(side="left", padx=4)

        tk.Button(
            btn_frame,
            text="Limpiar log",
            font=self.font_small,
            bg=BG_CARD, fg=TEXT_SEC,
            activebackground=BORDER,
            bd=0, padx=12, pady=10,
            cursor="hand2",
            command=self._clear_log,
            relief="flat",
        ).pack(side="left", padx=4)

        tk.Button(
            btn_frame,
            text="📄 Abrir log",
            font=self.font_small,
            bg=BG_CARD, fg=CYAN,
            activebackground=BORDER,
            activeforeground=CYAN,
            bd=0, padx=12, pady=10,
            cursor="hand2",
            command=self._abrir_log_archivo,
            relief="flat",
        ).pack(side="left", padx=4)

        # Progress bar
        self.progress = ttk.Progressbar(bottom, mode="indeterminate",
                                         length=300)
        self.progress.pack(pady=(6,0))
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TProgressbar",
                         troughcolor=BG_CARD,
                         background=ACCENT,
                         thickness=4)

        self.lbl_status = tk.Label(bottom, text="Listo",
                                    font=self.font_small,
                                    fg=TEXT_SEC, bg=BG_PANEL)
        self.lbl_status.pack(pady=(2,0))

    def _build_config_panel(self, parent):
        card = tk.Frame(parent, bg=BG_CARD,
                         highlightthickness=1,
                         highlightbackground=BORDER)
        card.pack(fill="x", pady=(0,10))

        tk.Label(card, text="CONFIGURACIÓN",
                 font=("Consolas", 9, "bold"),
                 fg=TEXT_SEC, bg=BG_CARD).pack(anchor="w", padx=12, pady=(10,4))
        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=12)

        fields = [
            ("Servidor URL",  "var_url",  self.config["BASE_URL"],  False),
            ("Usuario",       "var_user", self.config["USUARIO"],   False),
            ("Contraseña",    "var_pass", self.config["PASSWORD"],  True),
            ("Carpeta destino","var_dest", self.config["DESTINO"],  False),
        ]

        for label, attr, default, secret in fields:
            row = tk.Frame(card, bg=BG_CARD)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=label, font=self.font_small,
                     fg=TEXT_SEC, bg=BG_CARD, width=15, anchor="w").pack(side="left")
            var = tk.StringVar(value=default)
            setattr(self, attr, var)
            show = "*" if secret else ""
            entry = tk.Entry(row, textvariable=var, font=self.font_small,
                              bg=BG_DARK, fg=TEXT_PRI,
                              insertbackground=TEXT_PRI,
                              bd=0, highlightthickness=1,
                              highlightbackground=BORDER,
                              highlightcolor=CYAN,
                              relief="flat", show=show)
            entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(4,0))

        tk.Frame(card, height=8, bg=BG_CARD).pack()

    def _build_stats_panel(self, parent):
        card = tk.Frame(parent, bg=BG_CARD,
                         highlightthickness=1,
                         highlightbackground=BORDER)
        card.pack(fill="x", pady=(0,10))

        tk.Label(card, text="ESTADÍSTICAS DE SESIÓN",
                 font=("Consolas", 9, "bold"),
                 fg=TEXT_SEC, bg=BG_CARD).pack(anchor="w", padx=12, pady=(10,4))
        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=12)

        stats_row = tk.Frame(card, bg=BG_CARD)
        stats_row.pack(fill="x", padx=12, pady=10)

        self.stat_nuevas   = self._stat_widget(stats_row, "0", "Semanas\nnuevas", ACCENT)
        self.stat_omitidas = self._stat_widget(stats_row, "0", "Semanas\nexistentes", CYAN)
        self.stat_pdfs     = self._stat_widget(stats_row, "0", "PDFs\ndescargados", YELLOW)

        # ── Separador ─────────────────────────────────────────────────────────
        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=12)

        # ── Panel de validación disco vs servidor ──────────────────────────────
        tk.Label(card, text="VALIDACIÓN TOTAL DE PDFs",
                 font=("Consolas", 9, "bold"),
                 fg=TEXT_SEC, bg=BG_CARD).pack(anchor="w", padx=12, pady=(8,4))
        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=12)

        val_row = tk.Frame(card, bg=BG_CARD)
        val_row.pack(fill="x", padx=12, pady=(8,4))

        # Disco
        disco_col = tk.Frame(val_row, bg=BG_CARD)
        disco_col.pack(side="left", expand=True)
        self.stat_disco = tk.Label(disco_col, text="—",
                                    font=("Consolas", 20, "bold"),
                                    fg=CYAN, bg=BG_CARD)
        self.stat_disco.pack()
        tk.Label(disco_col, text="PDFs\nen disco", font=("Consolas", 8),
                 fg=TEXT_SEC, bg=BG_CARD).pack()

        # Ícono de comparación
        self.lbl_match_icon = tk.Label(val_row, text="  ↔  ",
                                        font=("Consolas", 16, "bold"),
                                        fg=TEXT_SEC, bg=BG_CARD)
        self.lbl_match_icon.pack(side="left")

        # Servidor
        srv_col = tk.Frame(val_row, bg=BG_CARD)
        srv_col.pack(side="left", expand=True)
        self.stat_servidor = tk.Label(srv_col, text="—",
                                       font=("Consolas", 20, "bold"),
                                       fg=YELLOW, bg=BG_CARD)
        self.stat_servidor.pack()
        tk.Label(srv_col, text="PDFs\nen servidor", font=("Consolas", 8),
                 fg=TEXT_SEC, bg=BG_CARD).pack()

        # Resultado de validación
        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(6,0))
        self.lbl_validacion = tk.Label(card, text="—  Sin datos aún",
                                        font=("Consolas", 9, "bold"),
                                        fg=TEXT_SEC, bg=BG_CARD)
        self.lbl_validacion.pack(pady=(4,6))

        # Botón contar disco
        btn_row = tk.Frame(card, bg=BG_CARD)
        btn_row.pack(pady=(0,8))
        tk.Button(
            btn_row,
            text="⟳  Contar PDFs en disco",
            font=self.font_small,
            bg=BG_DARK, fg=CYAN,
            activebackground=BORDER,
            activeforeground=CYAN,
            bd=0, padx=10, pady=5,
            cursor="hand2",
            command=self._contar_disco_manual,
            relief="flat",
        ).pack()

        # ── Separador final ────────────────────────────────────────────────────
        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=12)
        last_row = tk.Frame(card, bg=BG_CARD)
        last_row.pack(fill="x", padx=12, pady=8)
        tk.Label(last_row, text="Última sincronización:",
                 font=self.font_small, fg=TEXT_SEC, bg=BG_CARD).pack(side="left")
        self.lbl_last_sync = tk.Label(last_row, text="—",
                                       font=self.font_small,
                                       fg=CYAN, bg=BG_CARD)
        self.lbl_last_sync.pack(side="left", padx=4)

    def _stat_widget(self, parent, value, label, color):
        frame = tk.Frame(parent, bg=BG_CARD)
        frame.pack(side="left", expand=True)
        lbl_val = tk.Label(frame, text=value,
                            font=("Consolas", 22, "bold"),
                            fg=color, bg=BG_CARD)
        lbl_val.pack()
        tk.Label(frame, text=label, font=("Consolas", 8),
                 fg=TEXT_SEC, bg=BG_CARD).pack()
        return lbl_val

    # ── Conteo de PDFs en disco ───────────────────────────────────────────────
    def _contar_pdfs_disco(self) -> int:
        destino = Path(self.var_dest.get())
        if not destino.exists():
            return 0
        return sum(1 for _ in destino.rglob("*.pdf"))

    def _contar_disco_manual(self):
        total = self._contar_pdfs_disco()
        self.stat_disco.config(text=str(total))
        self._log(f"  Conteo manual en disco: {total} PDFs", "info")
        self._actualizar_validacion()

    def _actualizar_validacion(self):
        try:
            disco    = int(self.stat_disco.cget("text"))
            servidor = int(self.stat_servidor.cget("text"))
        except ValueError:
            return
        if disco == servidor:
            color = ACCENT;  icon = "  =  ";  texto = f"✔  COINCIDEN  ({disco} PDFs)"
        elif disco < servidor:
            diff  = servidor - disco
            color = YELLOW;  icon = "  <  ";  texto = f"⚠  FALTAN {diff} PDFs en disco"
        else:
            diff  = disco - servidor
            color = RED;     icon = "  >  ";  texto = f"✖  {diff} PDFs extra en disco"
        self.lbl_match_icon.config(text=icon, fg=color)
        self.lbl_validacion.config(text=texto, fg=color)

    # ── Log en disco ──────────────────────────────────────────────────────────
    def _init_log_file(self):
        """Crea/abre el archivo de log del día en la misma carpeta del .py."""
        fecha = datetime.now().strftime("%Y-%m-%d")
        self._log_path = LOG_DIR / f"log_{fecha}.txt"
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write("\n")
                f.write("=" * 54 + "\n")
                f.write(f"  SESIÓN INICIADA  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"  Archivo: {self._log_path.name}\n")
                f.write("=" * 54 + "\n")
        except Exception:
            self._log_path = None

    def _write_log_file(self, ts: str, msg: str, tag: str):
        """Escribe una línea al archivo de log del día (thread-safe)."""
        if not getattr(self, "_log_path", None):
            return
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        if self._log_path.stem != f"log_{fecha_hoy}":
            self._init_log_file()
        try:
            nivel = {"ok": "OK  ", "err": "ERR ", "warn": "WARN",
                     "info": "INFO", "dim": "    "}.get(tag, "    ")
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {nivel}  {msg}\n")
        except Exception:
            pass

    # ── Reloj ─────────────────────────────────────────────────────────────────
    def _tick_clock(self):
        now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        self.lbl_clock.config(text=now)
        self.after(1000, self._tick_clock)

    # ── Log helpers ───────────────────────────────────────────────────────────
    def _log(self, msg, tag="dim"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.config(state="normal")
        self.log_box.insert("end", f"[{ts}] ", "dim")
        self.log_box.insert("end", msg + "\n", tag)
        self.log_box.see("end")
        self.log_box.config(state="disabled")
        self._write_log_file(ts, msg, tag)

    def _clear_log(self):
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    def _abrir_log_archivo(self):
        """Abre el archivo de log del día en el Bloc de notas."""
        log_path = getattr(self, "_log_path", None)
        if log_path and log_path.exists():
            try:
                os.startfile(str(log_path))
            except Exception as exc:
                messagebox.showerror("Error", f"No se pudo abrir el log:\n{exc}")
        else:
            messagebox.showinfo(
                "Sin log",
                "No se encontró archivo de log para hoy.\n"
                f"Se guardará en:\n{LOG_DIR}"
            )

    def _set_status(self, msg):
        self.lbl_status.config(text=msg)

    def _update_last_sync_label(self):
        if self.last_sync:
            try:
                dt = datetime.fromisoformat(self.last_sync)
                self.lbl_last_sync.config(
                    text=dt.strftime("%d/%m/%Y %H:%M:%S"))
            except Exception:
                self.lbl_last_sync.config(text=self.last_sync)
        else:
            self.lbl_last_sync.config(text="Nunca")

    # ── Control de sincronización ─────────────────────────────────────────────
    def _start_sync(self):
        if self._running:
            return
        self._running = True
        self.btn_sync.config(state="disabled")
        self.btn_recuperar.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.progress.start(12)
        self.stat_nuevas.config(text="0")
        self.stat_omitidas.config(text="0")
        self.stat_pdfs.config(text="0")
        self.stat_disco.config(text="—")
        self.stat_servidor.config(text="—")
        self.lbl_match_icon.config(text="  ↔  ", fg=TEXT_SEC)
        self.lbl_validacion.config(text="Calculando…", fg=TEXT_SEC)
        self._set_status("Sincronizando…")
        self._thread = threading.Thread(target=self._run_sync, daemon=True)
        self._thread.start()

    def _start_recuperar(self):
        if self._running:
            return
        self._running = True
        self.btn_sync.config(state="disabled")
        self.btn_recuperar.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.progress.start(12)
        self.stat_pdfs.config(text="0")
        self.lbl_validacion.config(text="Recuperando faltantes…", fg=YELLOW)
        self._set_status("Recuperando faltantes…")
        self._thread = threading.Thread(target=self._run_recuperar, daemon=True)
        self._thread.start()

    def _stop_sync(self):
        self._running = False
        self._set_status("Cancelando…")

    def _finish_sync(self, ok=True):
        self._running = False
        self.progress.stop()
        self.btn_sync.config(state="normal")
        self.btn_recuperar.config(state="normal")
        self.btn_stop.config(state="disabled")
        self._set_status("Completado" if ok else "Cancelado / Error")

    # ── Lógica de sincronización (hilo aparte) ────────────────────────────────
    def _run_sync(self):
        url      = self.var_url.get().rstrip("/")
        usuario  = self.var_user.get()
        password = self.var_pass.get()
        destino  = self.var_dest.get()

        cred    = base64.b64encode(f"{usuario}:{password}".encode()).decode()
        session = requests.Session()
        session.headers.update({"Authorization": f"Basic {cred}"})
        session.verify = False

        self._log("══════════════════════════════════════", "info")
        self._log(" INICIO DE SINCRONIZACIÓN", "info")
        self._log(f" Servidor : {url}", "dim")
        self._log(f" Destino  : {destino}", "dim")
        self._log("══════════════════════════════════════", "info")

        # 1. Obtener semanas (el servidor sincroniza extraidos/ al responder)
        self._log("Consultando semanas disponibles…", "info")
        try:
            resp = session.get(f"{url}/api/facturacion/semanas/", timeout=60)
            resp.raise_for_status()
            semanas = resp.json().get("semanas", [])
            self._log(f"  → {len(semanas)} semanas encontradas.", "ok")
            total_servidor = sum(s.get("total_pdfs", 0) for s in semanas)
            self._log(f"  → {total_servidor} PDFs en servidor (extraidos/).", "ok")
            self.after(0, lambda v=total_servidor:
                        self.stat_servidor.config(text=str(v)))
        except Exception as exc:
            self._log(f"  ERROR al consultar semanas: {exc}", "err")
            self.after(0, lambda: self._finish_sync(False))
            return

        total_nuevas   = 0
        total_omitidas = 0
        total_pdfs     = 0

        # 2. Iterar semanas
        for sem in semanas:
            if not self._running:
                self._log("⚠  Sincronización cancelada por el usuario.", "warn")
                break

            key    = sem.get("key", "")
            year   = sem.get("year", "")
            mes    = sem.get("mes", "")
            semana = sem.get("semana", "")
            pdfs_esperados = sem.get("total_pdfs", 0)

            carpeta = Path(destino) / str(year) / str(mes) / str(semana)

            if carpeta.exists():
                pdfs_locales = list(carpeta.glob("*.pdf"))
                if pdfs_locales:
                    n_local = len(pdfs_locales)
                    diff    = pdfs_esperados - n_local
                    if diff == 0:
                        estado = f"({n_local} PDFs  ✔)"
                        tag    = "dim"
                    elif diff > 0:
                        estado = f"({n_local}/{pdfs_esperados} PDFs  ⚠ faltan {diff})"
                        tag    = "warn"
                    else:
                        estado = f"({n_local}/{pdfs_esperados} PDFs  ! extra {abs(diff)})"
                        tag    = "err"
                    self._log(f"  [=] {key}  {estado}", tag)
                    total_omitidas += 1
                    self.after(0, lambda v=total_omitidas:
                                self.stat_omitidas.config(text=str(v)))
                    continue

            self._log(f"  [↓] {key}  ({pdfs_esperados} PDFs esperados)…", "warn")
            dl_url  = f"{url}/api/facturacion/descargar-pdfs/?semana={requests.utils.quote(key)}"
            tmp_zip = tempfile.mktemp(suffix=".zip")

            try:
                r = session.get(dl_url, timeout=180, stream=True)
                r.raise_for_status()
                with open(tmp_zip, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if not self._running:
                            break
                        f.write(chunk)
            except Exception as exc:
                self._log(f"       ERROR descargando: {exc}", "err")
                if os.path.exists(tmp_zip):
                    os.remove(tmp_zip)
                continue

            try:
                carpeta.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(tmp_zip, "r") as zf:
                    zf.extractall(carpeta)
                extraidos = len(list(carpeta.glob("*.pdf")))
                self._log(f"       ✓ {extraidos} PDFs extraídos", "ok")
                total_nuevas += 1
                total_pdfs   += extraidos
                self.after(0, lambda v=total_nuevas:
                            self.stat_nuevas.config(text=str(v)))
                self.after(0, lambda v=total_pdfs:
                            self.stat_pdfs.config(text=str(v)))
            except Exception as exc:
                self._log(f"       FALLO extrayendo ZIP: {exc}", "err")
            finally:
                if os.path.exists(tmp_zip):
                    os.remove(tmp_zip)

        # 3. Resumen
        ahora = datetime.now()
        self.last_sync = ahora.isoformat()
        self.save_state()

        self._log("══════════════════════════════════════", "info")
        self._log(f"  Semanas nuevas       : {total_nuevas}", "ok")
        self._log(f"  Semanas ya existentes: {total_omitidas}", "dim")
        self._log(f"  PDFs nuevos descarg. : {total_pdfs}", "ok")

        total_disco = self._contar_pdfs_disco()

        # ── Desglose por semana (disco vs servidor) ───────────────────────────
        self._log("──────────────────────────────────────", "dim")
        self._log("  DESGLOSE POR SEMANA  [disco / servidor]", "info")
        for sem in semanas:
            key    = sem.get("key", "")
            year   = sem.get("year", "")
            mes    = sem.get("mes", "")
            semana = sem.get("semana", "")
            esperados = sem.get("total_pdfs", 0)
            carpeta = Path(destino) / str(year) / str(mes) / str(semana)
            locales = len(list(carpeta.glob("*.pdf"))) if carpeta.exists() else 0
            diff    = esperados - locales
            if diff == 0:
                marca = "✔"; tag = "ok"
            elif diff > 0:
                marca = f"⚠ -{diff}"; tag = "warn"
            else:
                marca = f"! +{abs(diff)}"; tag = "err"
            self._log(f"  {key:<30}  {locales:>4} / {esperados:<4}  {marca}", tag)

        self._log("──────────────────────────────────────", "dim")
        self._log(f"  PDFs en disco        : {total_disco}", "info")
        self._log(f"  PDFs en servidor     : {total_servidor}", "info")
        if total_disco == total_servidor:
            self._log(f"  ✔ VALIDACIÓN OK — totales coinciden ({total_disco})", "ok")
        elif total_disco < total_servidor:
            self._log(f"  ⚠ FALTAN {total_servidor - total_disco} PDFs en disco", "warn")
        else:
            self._log(f"  ! {total_disco - total_servidor} PDFs extra en disco", "err")

        self._log(f"  Finalizado: {ahora.strftime('%d/%m/%Y %H:%M:%S')}", "info")
        self._log("══════════════════════════════════════", "info")

        self.after(0, lambda v=total_disco: self.stat_disco.config(text=str(v)))
        self.after(0, self._actualizar_validacion)
        self.after(0, self._update_last_sync_label)
        self.after(0, lambda: self._finish_sync(True))

    # ── Recuperar semanas con PDFs faltantes ──────────────────────────────────
    def _run_recuperar(self):
        """Re-descarga SOLO las semanas donde disco < servidor."""
        url      = self.var_url.get().rstrip("/")
        usuario  = self.var_user.get()
        password = self.var_pass.get()
        destino  = self.var_dest.get()

        cred    = base64.b64encode(f"{usuario}:{password}".encode()).decode()
        session = requests.Session()
        session.headers.update({"Authorization": f"Basic {cred}"})
        session.verify = False

        self._log("══════════════════════════════════════", "warn")
        self._log(" RECUPERACIÓN DE PDFs FALTANTES", "warn")
        self._log("══════════════════════════════════════", "warn")

        # 1. Obtener lista de semanas del servidor (sincroniza extraidos/ al responder)
        try:
            resp    = session.get(f"{url}/api/facturacion/semanas/", timeout=60)
            resp.raise_for_status()
            semanas = resp.json().get("semanas", [])
        except Exception as exc:
            self._log(f"  ERROR consultando semanas: {exc}", "err")
            self.after(0, lambda: self._finish_sync(False))
            return

        total_srv = sum(s.get("total_pdfs", 0) for s in semanas)

        # 2. Identificar semanas con faltantes
        faltantes = []
        for sem in semanas:
            key       = sem.get("key", "")
            year      = sem.get("year", "")
            mes       = sem.get("mes", "")
            semana    = sem.get("semana", "")
            esperados = sem.get("total_pdfs", 0)
            carpeta   = Path(destino) / str(year) / str(mes) / str(semana)
            locales   = len(list(carpeta.glob("*.pdf"))) if carpeta.exists() else 0
            if locales < esperados:
                faltantes.append({
                    "key": key, "carpeta": carpeta,
                    "locales": locales, "esperados": esperados,
                    "diff": esperados - locales,
                })

        if not faltantes:
            self._log("  ✔ No hay faltantes — todos los PDFs están completos.", "ok")
            self.after(0, lambda: self._finish_sync(True))
            return

        self._log(f"  Semanas con faltantes: {len(faltantes)}", "warn")
        self._log(f"  PDFs pendientes total: {sum(f['diff'] for f in faltantes)}", "warn")
        self._log("──────────────────────────────────────", "dim")

        total_recuperados = 0
        total_semanas_ok  = 0

        for item in faltantes:
            if not self._running:
                self._log("⚠  Recuperación cancelada por el usuario.", "warn")
                break

            key       = item["key"]
            carpeta   = item["carpeta"]
            locales   = item["locales"]
            esperados = item["esperados"]
            diff      = item["diff"]

            self._log(
                f"  [↓] {key}  (tiene {locales}, faltan {diff} de {esperados})…",
                "warn")

            dl_url  = f"{url}/api/facturacion/descargar-pdfs/?semana={requests.utils.quote(key)}"
            tmp_zip = tempfile.mktemp(suffix=".zip")
            tmp_dir = Path(tempfile.mkdtemp())

            try:
                r = session.get(dl_url, timeout=180, stream=True)
                r.raise_for_status()
                with open(tmp_zip, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if not self._running:
                            break
                        f.write(chunk)
            except Exception as exc:
                self._log(f"       ERROR descargando: {exc}", "err")
                if os.path.exists(tmp_zip):
                    os.remove(tmp_zip)
                try:
                    import shutil; shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass
                continue

            try:
                import shutil
                carpeta.mkdir(parents=True, exist_ok=True)

                with zipfile.ZipFile(tmp_zip, "r") as zf:
                    zf.extractall(tmp_dir)

                existentes  = {f.name.lower() for f in carpeta.glob("*.pdf")}
                pdfs_en_zip = list(tmp_dir.rglob("*.pdf"))
                copiados = 0
                ya_tenia = 0
                for pdf_src in pdfs_en_zip:
                    if pdf_src.name.lower() not in existentes:
                        shutil.copy2(pdf_src, carpeta / pdf_src.name)
                        copiados += 1
                    else:
                        ya_tenia += 1

                nuevos_total = len(list(carpeta.glob("*.pdf")))
                if nuevos_total >= esperados:
                    self._log(
                        f"       ✔ {nuevos_total} PDFs  "
                        f"(+{copiados} copiados, {ya_tenia} ya existían)", "ok")
                    total_semanas_ok += 1
                else:
                    falt_rest = esperados - nuevos_total
                    self._log(
                        f"       ⚠ {nuevos_total}/{esperados} PDFs  "
                        f"(+{copiados} copiados, aún faltan {falt_rest})", "warn")

                total_recuperados += copiados

            except Exception as exc:
                self._log(f"       FALLO extrayendo ZIP: {exc}", "err")
            finally:
                if os.path.exists(tmp_zip):
                    os.remove(tmp_zip)
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass

        # 3. Resumen final
        ahora = datetime.now()
        self.last_sync = ahora.isoformat()
        self.save_state()

        total_disco = self._contar_pdfs_disco()

        self._log("──────────────────────────────────────", "dim")
        self._log(f"  Semanas reparadas    : {total_semanas_ok}/{len(faltantes)}", "ok")
        self._log(f"  PDFs recuperados     : {total_recuperados}", "ok")
        self._log(f"  PDFs en disco ahora  : {total_disco}", "info")
        self._log(f"  PDFs en servidor     : {total_srv}", "info")
        if total_disco >= total_srv:
            self._log(f"  ✔ VALIDACIÓN OK — disco cubre servidor ({total_disco})", "ok")
        else:
            self._log(
                f"  ⚠ Aún faltan {total_srv - total_disco} PDFs en disco", "warn")
        self._log(f"  Finalizado: {ahora.strftime('%d/%m/%Y %H:%M:%S')}", "info")
        self._log("══════════════════════════════════════", "warn")

        self.after(0, lambda v=total_disco: self.stat_disco.config(text=str(v)))
        self.after(0, lambda v=total_srv:   self.stat_servidor.config(text=str(v)))
        self.after(0, lambda v=total_recuperados:
                    self.stat_pdfs.config(text=str(v)))
        self.after(0, self._actualizar_validacion)
        self.after(0, self._update_last_sync_label)
        self.after(0, lambda: self._finish_sync(True))


# ── Punto de entrada ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    app = SincronizadorApp()
    app.mainloop()
