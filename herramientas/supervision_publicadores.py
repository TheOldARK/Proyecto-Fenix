"""Supervisión acotada de procesos: un hijo vivo no implica progreso."""
import json
import os
import signal
import subprocess
import time


def leer_documento(ruta):
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def detener_arbol(proceso):
    """Solo termina el proceso iniciado por el gestor y sus descendientes."""
    if proceso.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proceso.pid), "/T", "/F"],
                capture_output=True, timeout=20, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            # taskkill puede no estar disponible o agotar su propio tiempo;
            # como mínimo termina el proceso que este gestor inició.
            pass
        if proceso.poll() is None:
            proceso.kill()
    else:
        # Los hijos supervisados se lanzan en su propia sesión.
        try:
            os.killpg(proceso.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proceso.wait(timeout=10)


def supervisar(proceso, estado_path, resultado_path, intento_id, detener, informar,
               sin_avance=600, max_duracion=14400, gracia_salida=15,
               intervalo=0.8, reloj=time.monotonic):
    inicio = ultimo_avance = reloj()
    firma_anterior = None
    final_desde = None
    resultado = {}
    while proceso.poll() is None:
        ahora = reloj()
        estado = leer_documento(estado_path)
        # Nunca interpretar un estado/resultado de un intento anterior.
        if estado.get("intento_id") == intento_id:
            firma = tuple(str(estado.get(k)) for k in ("estado", "mensaje", "progreso", "fase"))
            if firma != firma_anterior:
                ultimo_avance = ahora
                firma_anterior = firma
                informar(estado)
        resultado = leer_documento(resultado_path)
        terminado = (
            resultado.get("intento_id") == intento_id
            and resultado.get("estado") in {"completado", "error"}
        )
        if terminado:
            if final_desde is None:
                final_desde = ahora
            if ahora - final_desde >= gracia_salida:
                detener_arbol(proceso)
                return resultado, "El resultado se guardó; se liberó el proceso que no cerraba."
        if detener.is_set():
            detener_arbol(proceso)
            return {"estado": "error", "error": "Cancelado por el usuario."}, ""
        if ahora - ultimo_avance >= sin_avance or ahora - inicio >= max_duracion:
            motivo = (f"Timeout: {sin_avance} s sin cambios de progreso."
                      if ahora - ultimo_avance >= sin_avance
                      else f"Timeout: se superó el límite de {max_duracion} s del intento.")
            detener_arbol(proceso)
            return {"estado": "error", "error": motivo}, ""
        detener.wait(intervalo)
    resultado = leer_documento(resultado_path)
    if resultado.get("intento_id") != intento_id:
        return {"estado": "error", "error": f"El proceso terminó con código {proceso.returncode} sin resultado válido."}, ""
    return resultado, ""
