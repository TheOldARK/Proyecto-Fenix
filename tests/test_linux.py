import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

from infraestructura.sia import runtime_navegador
from servicios import actualizacion_aplicacion as actualizador


class LinuxTests(unittest.TestCase):
    def test_datos_xdg_y_alternativa_segura(self):
        archivo = Path(__file__).resolve().parents[1] / 'configuracion.py'
        with tempfile.TemporaryDirectory() as temporal:
            for xdg, esperado in [('', Path.home() / '.local/share/Fenix'),
                                  ('relativo', Path.home() / '.local/share/Fenix'),
                                  (temporal, Path(temporal) / 'Fenix')]:
                with self.subTest(xdg=xdg), patch.object(sys, 'platform', 'linux'), \
                     patch.dict(os.environ, {'FENIX_DATA_DIR': '', 'XDG_DATA_HOME': xdg}):
                    self.assertEqual(runpy.run_path(str(archivo))['CARPETA_DATOS'], esperado.resolve())
            with patch.object(sys, 'platform', 'linux'), patch.dict(os.environ, {'FENIX_DATA_DIR': temporal}):
                self.assertEqual(runpy.run_path(str(archivo))['CARPETA_DATOS'], Path(temporal).resolve())

    def test_navegador_linux_y_copia_ausente(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            navegador = raiz / 'browser/chrome-headless-shell-linux64/chrome-headless-shell'
            navegador.parent.mkdir(parents=True)
            navegador.touch()
            with patch.object(sys, 'platform', 'linux'), patch.object(sys, 'frozen', True, create=True), \
                 patch.object(sys, 'executable', str(raiz / 'Fenix')):
                self.assertEqual(runtime_navegador.ejecutable_integrado(), str(navegador))
                navegador.unlink()
                with self.assertRaises(FileNotFoundError):
                    runtime_navegador.ejecutable_integrado()

    def test_solo_ofrece_tar_linux(self):
        releases = [{'tag_name': 'v2.1.2', 'assets': [
            {'name': nombre, 'browser_download_url': 'https://example.com/' + nombre}
            for nombre in ('Fenix-2.1.2-windows-x64.zip', 'Fenix-2.1.2-macos-x64.zip',
                           'Fenix-2.1.2-linux-x64.tar.gz')]}]
        with patch.object(sys, 'platform', 'linux'), \
             patch.object(actualizador.platform, 'machine', return_value='x86_64'), \
             patch.object(actualizador, 'urlopen', return_value=io.BytesIO(json.dumps(releases).encode())):
            release = actualizador.consultar_ultima_version()
            self.assertEqual(release['asset'], 'Fenix-2.1.2-linux-x64.tar.gz')
            self.assertTrue(release['instalacion_manual'])
            self.assertTrue(actualizador.hay_actualizacion(release))

    def test_sin_paquete_linux_no_bloquea_arranque(self):
        with patch.object(sys, 'platform', 'linux'), \
             patch.object(actualizador.platform, 'machine', return_value='x86_64'), \
             patch.object(actualizador, 'urlopen', return_value=io.BytesIO(b'[]')):
            release = actualizador.consultar_ultima_version()
            self.assertTrue(release['sin_paquete_compatible'])
            self.assertFalse(actualizador.hay_actualizacion(release))

    def test_no_usa_updater_windows(self):
        with patch.object(sys, 'platform', 'linux'):
            with self.assertRaisesRegex(RuntimeError, 'Linux'):
                actualizador.iniciar_reemplazo('paquete.tar.gz', 123)
            with self.assertRaisesRegex(RuntimeError, 'Linux'):
                actualizador.descargar_release({})

    def test_no_ofrece_x64_a_arm(self):
        with patch.object(sys, 'platform', 'linux'), \
             patch.object(actualizador.platform, 'machine', return_value='aarch64'):
            with self.assertRaises(ValueError):
                actualizador.nombre_paquete('2.1.1')


if __name__ == '__main__':
    unittest.main()
