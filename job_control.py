"""
Control de ejecución de jobs (pausa / reanudación / abort) compartido por
todos los servicios (histórico, clasificación, extracción).

Convención del pause_event:
    SET   = job corriendo
    CLEAR = job pausado
"""
import logging


def wait_if_paused(pause_event, abort_event=None, logger=None):
    """
    Si el job está pausado (pause_event en estado CLEAR), bloquea en este punto
    —que debe ser siempre un límite seguro ENTRE documentos— hasta que se
    reanude. Mientras está pausado permanece sensible al abort.

    Devuelve True si el job debe ABORTAR, False si puede continuar.
    """
    log = logger or logging.getLogger()

    if abort_event is not None and abort_event.is_set():
        return True

    if pause_event is not None and not pause_event.is_set():
        log.warning("⏸ Pausado — esperando reanudar...")
        while not pause_event.is_set():
            if abort_event is not None and abort_event.is_set():
                log.warning("⏹ Abort recibido durante la pausa.")
                return True
            pause_event.wait(timeout=0.4)
        # El abort también despausa (set) para liberar el wait: al salir del
        # loop hay que confirmar que la salida fue por reanudación y no por abort.
        if abort_event is not None and abort_event.is_set():
            log.warning("⏹ Abort recibido durante la pausa.")
            return True
        log.info("▶ Reanudado.")

    return False
