"""Prueba explícita del botón real de actualización desde el EXE empaquetado.

Solo se activa con --prueba-actualizacion CONFIG.json y datos de prueba aislados.
"""
import json
import os
import subprocess
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from aplicacion.interfaz import VentanaPrincipal
from servicios import actualizacion_aplicacion as actualizador


def ejecutar(config):
    datos = json.loads(Path(config).read_text(encoding='utf-8'))
    if not os.environ.get('FENIX_DATA_DIR'):
        raise RuntimeError('La prueba requiere FENIX_DATA_DIR aislado.')
    actualizador.API_RELEASES = datos['api']
    original = actualizador.iniciar_reemplazo

    def iniciar(*args, **kwargs):
        job = original(*args, **kwargs)
        Path(datos['job']).write_text(json.dumps(job), encoding='utf-8')
        return job

    actualizador.iniciar_reemplazo = iniciar
    QMessageBox.question = lambda *a, **k: QMessageBox.StandardButton.Yes
    app = QApplication([])
    errores = []

    def error(*args):
        errores.append(str(args[-1]))
        app.quit()

    QMessageBox.critical = error
    ventana = VentanaPrincipal()
    ventana.show()
    if datos.get('worker'):
        ventana.proceso_actualizacion = subprocess.Popen(datos['worker'])
    # La ventana está abierta antes de activar el mismo método del botón.
    QTimer.singleShot(1500, ventana.buscar_actualizacion_aplicacion)
    QTimer.singleShot(180000, app.quit)
    app.exec()
    if errores:
        Path(datos['job'] + '.error').write_text('\n'.join(errores), encoding='utf-8')
        return 1
    return 0 if Path(datos['job']).is_file() else 2
