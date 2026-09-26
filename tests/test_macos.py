import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

from servicios import actualizacion_aplicacion as actualizador
from infraestructura.sia import runtime_navegador


class MacOSTests(unittest.TestCase):
    def test_datos_en_application_support_y_directorio_personalizable(self):
        archivo = Path(__file__).resolve().parents[1] / 'configuracion.py'
        with patch.object(sys, 'platform', 'darwin'), patch.dict(os.environ, {'FENIX_DATA_DIR': ''}):
            config = runpy.run_path(str(archivo))
            self.assertEqual(config['CARPETA_DATOS'], (Path.home() / 'Library/Application Support/Fenix').resolve())
        with tempfile.TemporaryDirectory() as datos:
            with patch.object(sys, 'platform', 'darwin'), patch.dict(os.environ, {'FENIX_DATA_DIR': datos}):
                self.assertEqual(runpy.run_path(str(archivo))['CARPETA_DATOS'], Path(datos).resolve())

    def test_chromium_dentro_del_bundle(self):
        with tempfile.TemporaryDirectory() as carpeta:
            contents = Path(carpeta) / 'Fenix.app/Contents'
            navegador = contents / 'Resources/browser/chrome-headless-shell-mac-arm64/headless_shell'
            navegador.parent.mkdir(parents=True)
            navegador.touch()
            with patch.object(sys, 'platform', 'darwin'), patch.object(sys, 'frozen', True, create=True), \
                 patch.object(sys, 'executable', str(contents / 'MacOS/Fenix')):
                self.assertEqual(runtime_navegador.ejecutable_integrado(), str(navegador))
                navegador.unlink()
                with self.assertRaises(FileNotFoundError):
                    runtime_navegador.ejecutable_integrado()

    def test_windows_conserva_su_navegador(self):
        with patch.object(sys, 'platform', 'win32'), patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(runtime_navegador.ejecutable_integrado(),
                             str(Path(sys.executable).parent / 'browser/chrome-headless-shell.exe'))

    def test_actualizaciones_separadas_por_plataforma_y_arquitectura(self):
        releases = [
            {'tag_name': 'v2.1.1', 'assets': [
                {'name': f'Fenix-2.1.1-{plataforma}.zip', 'browser_download_url': 'https://example.com/' + plataforma}
                for plataforma in ('windows-x64', 'macos-arm64', 'macos-x64')]},
            {'tag_name': 'v9.0.0', 'assets': [{'name': 'Fenix-9.0.0-windows-x64.zip', 'browser_download_url': 'https://example.com/windows'}]},
        ]
        for arquitectura, sufijo in [('arm64', 'arm64'), ('x86_64', 'x64')]:
            with self.subTest(arquitectura=arquitectura), patch.object(sys, 'platform', 'darwin'), \
                 patch.object(actualizador.platform, 'machine', return_value=arquitectura), \
                 patch.object(actualizador, 'urlopen', return_value=io.BytesIO(json.dumps(releases).encode())), \
                 patch.object(actualizador, 'VERSION', '2.0.8'):
                release = actualizador.consultar_ultima_version()
                self.assertEqual(release['asset'], f'Fenix-2.1.1-macos-{sufijo}.zip')
                self.assertTrue(release['instalacion_manual'])
                self.assertTrue(actualizador.hay_actualizacion(release))
                self.assertFalse(actualizador.hay_actualizacion({'version': '9.0.0', 'asset': 'Fenix-9.0.0-windows-x64.zip'}))

    def test_sin_mac_publicado_no_ofrece_paquetes_windows(self):
        with patch.object(sys, 'platform', 'darwin'), \
             patch.object(actualizador, 'urlopen', return_value=io.BytesIO(b'[]')):
            release = actualizador.consultar_ultima_version()
            self.assertTrue(release['sin_paquete_compatible'])
            self.assertFalse(actualizador.hay_actualizacion(release))

    def test_no_ejecuta_instalador_windows_en_mac(self):
        with patch.object(sys, 'platform', 'darwin'):
            with self.assertRaisesRegex(RuntimeError, 'Fenix.app'):
                actualizador.iniciar_reemplazo('paquete.zip', 123)
            with self.assertRaisesRegex(RuntimeError, 'Fenix.app'):
                actualizador.descargar_release({})


if __name__ == '__main__':
    unittest.main()
