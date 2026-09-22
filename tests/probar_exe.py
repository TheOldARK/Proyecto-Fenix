"""Ejercita descarga, botón Qt, instalador externo, diagnóstico y relanzamiento."""
import functools
import hashlib
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from servicios.instalador import extraer_verificado, verificar_instalacion, ruta_larga, MANIFIESTO, sha256


def ejecutar(viejo, nuevo, escenario):
    base = Path(tempfile.mkdtemp(prefix='e2e-' + escenario + '-', dir=r'D:\Fenix-Pruebas'))
    padre = base / 'Jose Zapata' / 'Downloads' / ('Carpeta de instalacion de Fenix con nombre largo ' * 2).strip()
    padre.mkdir(parents=True)
    instalacion = padre / 'Fenix-1.0.8-windows-x64'
    extraer_verificado(viejo, instalacion, base)
    datos = base / 'datos-aislados'
    datos.mkdir()
    sentinel = datos / 'horario-personal-prueba.json'
    sentinel.write_text('{"conservar": true}', encoding='utf-8')
    version = '1.0.8.1'
    if escenario == 'origen-incompleto':
        dat = next(ruta_larga(instalacion).rglob('privacy-sandbox-attestations.dat'))
        dat.unlink()
    digest = sha256(nuevo)
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            if self.path == '/releases':
                cuerpo = json.dumps([{'tag_name': 'v' + version, 'assets': [{
                    'name': f'Fenix-{version}-windows-x64.zip', 'size': nuevo.stat().st_size,
                    'digest': 'sha256:' + digest,
                    'browser_download_url': f'http://127.0.0.1:{self.server.server_port}/{nuevo.name}'}]}]).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(cuerpo)
            else:
                super().do_GET()
    servidor = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(nuevo.parent)))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    config = {'api': f'http://127.0.0.1:{servidor.server_port}/releases', 'job': str(base / 'job.json')}
    if escenario == 'worker-activo':
        chromium = next(ruta_larga(instalacion).rglob('chrome-headless-shell.exe'))
        # Playwright/Node recibe la ruta normal; el prefijo extendido es para E/S del instalador.
        chromium = str(chromium).removeprefix('\\\\?\\')
        config['worker'] = [sys.executable, str(Path(__file__).with_name('worker_navegador.py')), chromium, str(base / 'worker.ready')]
    configuracion = base / 'prueba.json'
    configuracion.write_text(json.dumps(config), encoding='utf-8')
    entorno = os.environ.copy()
    entorno['FENIX_DATA_DIR'] = str(datos)
    entorno['QT_QPA_PLATFORM'] = 'offscreen'
    entorno['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    proceso = subprocess.Popen([str(instalacion / 'Fenix.exe'), '--prueba-actualizacion', str(configuracion)], cwd=base, env=entorno)
    resultado = None
    try:
        codigo = proceso.wait(timeout=200)
        assert codigo == 0, f'La interfaz terminó con {codigo}; revisar {base}'
        job = json.loads(Path(config['job']).read_text(encoding='utf-8'))
        limite = time.monotonic() + 180
        while not Path(job['resultado']).exists() and time.monotonic() < limite:
            time.sleep(0.5)
        resultado = json.loads(Path(job['resultado']).read_text(encoding='utf-8'))
        assert resultado['ok'], resultado
        assert resultado['version'] == version
        manifiesto = json.loads((instalacion / MANIFIESTO).read_text(encoding='utf-8'))
        verificar_instalacion(instalacion, manifiesto)
        assert sentinel.read_text(encoding='utf-8') == '{"conservar": true}'
        dat = next(ruta_larga(instalacion).rglob('privacy-sandbox-attestations.dat'))
        assert dat.stat().st_size > 0
        diagnostico = Path(resultado['log']).parent / 'diagnostico/logs/diagnostico_instalacion.json'
        assert json.loads(diagnostico.read_text(encoding='utf-8'))['correcto']
        if escenario == 'worker-activo':
            assert (base / 'worker.ready').exists(), 'No se inició el worker'
            assert (base / 'worker.ready.cerrado').exists(), 'Chromium no confirmó el cierre'
        time.sleep(3)
        logs = (datos / 'logs/interfaz.log').read_text(encoding='utf-8')
        assert '1.0.8.1' in logs, 'No arrancó la nueva interfaz'
        informe = {'ok': True, 'escenario': escenario, 'archivos_verificados': len(manifiesto['files']),
                   'ruta_dat_longitud': len(str(dat)), 'resultado': resultado, 'datos_preservados': True}
        (base / 'informe.json').write_text(json.dumps(informe, indent=2), encoding='utf-8')
        print(json.dumps(informe), flush=True)
    finally:
        servidor.shutdown()
        if proceso.poll() is None:
            subprocess.run(['taskkill', '/PID', str(proceso.pid), '/T', '/F'], capture_output=True)
        if resultado and resultado.get('pid'):
            # Solo terminar el proceso de prueba recién creado, nunca otras instalaciones.
            subprocess.run(['taskkill', '/PID', str(resultado['pid']), '/T', '/F'], capture_output=True)
    return base


if __name__ == '__main__':
    ejecutar(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
