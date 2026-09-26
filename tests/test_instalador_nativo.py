from contextlib import nullcontext
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from herramientas import instalacion_nativa as n


def release(version, sistema='linux-x64', **otros):
    extension = '.zip' if sistema.startswith('macos-') else '.tar.gz'
    nombre = f'Fenix-{version}-{sistema}{extension}'
    return {'tag_name': 'v' + version, 'assets': [
        {'name': nombre, 'browser_download_url': n.PREFIJO_DESCARGA + 'v' + version + '/' + nombre,
         'size': 100, 'digest': 'sha256:' + 'a' * 64}], **otros}


class InstaladorNativoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raiz = Path(self.temp.name)
        self.cancelar = threading.Event()
        self.progreso = lambda *args: None

    def test_seleccion_exacta_y_version_numerica(self):
        releases = [release('9.0.0', 'windows-x64'), release('2.9.0'), release('2.10.0'),
                    release('3.0.0', prerelease=True), release('4.0.0', draft=True), release('2.10.0.1')]
        self.assertEqual(n.seleccionar_release(releases, 'linux-x64')['version'], '2.10.0.1')
        with self.assertRaises(RuntimeError):
            n.seleccionar_release(releases, 'macos-arm64')

    def test_no_elige_paquete_de_otro_mac(self):
        releases = [release('2.1.1', 'macos-arm64'), release('9.0.0', 'macos-x64')]
        self.assertEqual(n.seleccionar_release(releases, 'macos-arm64')['version'], '2.1.1')

    def test_rechaza_url_ajena(self):
        dato = release('2.1.1')
        dato['assets'][0]['browser_download_url'] = 'https://example.com/fenix.tar.gz'
        with self.assertRaises(RuntimeError):
            n.seleccionar_release([dato], 'linux-x64')

    def test_sistemas_y_arquitecturas(self):
        for sistema, arch, esperado in [('darwin', 'arm64', 'macos-arm64'), ('darwin', 'x86_64', 'macos-x64'), ('linux', 'x86_64', 'linux-x64')]:
            with patch.object(sys, 'platform', sistema), patch.object(n.platform, 'machine', return_value=arch):
                self.assertEqual(n.plataforma_nativa(), esperado)
        with patch.object(sys, 'platform', 'linux'), patch.object(n.platform, 'machine', return_value='aarch64'):
            with self.assertRaises(RuntimeError):
                n.plataforma_nativa()

    def test_consulta_sha_y_cancelacion(self):
        with patch.object(n, 'abrir_url', return_value=io.BytesIO(json.dumps([release('2.1.1')]).encode())):
            self.assertEqual(n.consultar_release('linux-x64', self.cancelar)['sha256'], 'a' * 64)
        self.cancelar.set()
        with self.assertRaises(n.Cancelado):
            n.consultar_release('linux-x64', self.cancelar)

    def test_checksum_complementario(self):
        dato = release('2.1.1')
        asset = dato['assets'][0]
        asset.pop('digest')
        dato['assets'].append({'name': asset['name'] + '.sha256', 'browser_download_url': asset['browser_download_url'] + '.sha256'})
        with patch.object(n, 'abrir_url', side_effect=[io.BytesIO(json.dumps([dato]).encode()), io.BytesIO(('b' * 64 + '  ' + asset['name']).encode())]):
            self.assertEqual(n.consultar_release('linux-x64', self.cancelar)['sha256'], 'b' * 64)

    def test_descarga_integridad_y_reintento(self):
        datos = b'paquete seguro'
        info = {'url': 'https://example.com/', 'version': '2.1.1', 'tamano': len(datos), 'sha256': hashlib.sha256(datos).hexdigest()}
        ruta = self.raiz / 'paquete'
        with patch.object(n, 'abrir_url', side_effect=[io.BytesIO(datos[:2]), io.BytesIO(datos)]), patch.object(self.cancelar, 'wait'):
            n.descargar(info, ruta, self.cancelar, self.progreso)
        self.assertEqual(ruta.read_bytes(), datos)
        info['sha256'] = '0' * 64
        with patch.object(n, 'abrir_url', return_value=io.BytesIO(datos)), self.assertRaisesRegex(RuntimeError, 'SHA-256'):
            n.descargar(info, ruta, self.cancelar, self.progreso)

    def test_descarga_no_ignora_cancelacion(self):
        self.cancelar.set()
        with self.assertRaises(n.Cancelado):
            n.descargar({}, self.raiz / 'paquete', self.cancelar, self.progreso)

    def zip(self, entradas):
        ruta = self.raiz / 'paquete.zip'
        with zipfile.ZipFile(ruta, 'w') as z:
            for nombre, datos, modo in entradas:
                info = zipfile.ZipInfo(nombre)
                info.create_system = 3
                info.external_attr = modo << 16
                z.writestr(info, datos)
        return ruta

    def extraer_zip(self, entradas):
        salida = self.raiz / 'extraido'
        salida.mkdir(exist_ok=True)
        return n.extraer(self.zip(entradas), salida, 'macos-arm64', self.cancelar, self.progreso)

    def test_zip_normal(self):
        carpeta = self.extraer_zip([('Fenix.app/Contents/MacOS/Fenix', b'binario', stat.S_IFREG | 0o755)])
        self.assertEqual((carpeta / 'Contents/MacOS/Fenix').read_bytes(), b'binario')

    def test_zip_traversal_y_duplicados(self):
        for entradas in [[('../fuera', b'X', 0o644)], [('Fenix.app/../../fuera', b'X', 0o644)],
                         [('/Fenix.app/file', b'X', 0o644)], [('Otra.app/file', b'X', 0o644)],
                         [('Fenix.app/file', b'X', 0o644), ('Fenix.app/file', b'Y', 0o644)]]:
            with self.subTest(entradas=entradas), self.assertRaises(RuntimeError):
                self.extraer_zip(entradas)
        self.assertFalse((self.raiz / 'fuera').exists())

    def test_no_escribe_debajo_de_enlaces(self):
        with self.assertRaises(RuntimeError):
            self.extraer_zip([('Fenix.app/link', '../../fuera', stat.S_IFLNK | 0o777),
                              ('Fenix.app/link/archivo', b'X', stat.S_IFREG | 0o644)])

    def test_rechaza_enlace_externo(self):
        with self.assertRaises(RuntimeError):
            self.extraer_zip([('Fenix.app/link', '../../fuera', stat.S_IFLNK | 0o777)])

    @unittest.skipIf(os.name == 'nt', 'Los enlaces y permisos se verifican en el sistema nativo.')
    def test_enlaces_internos_y_permisos(self):
        carpeta = self.extraer_zip([('Fenix.app/Contents/MacOS/Fenix', b'binario', stat.S_IFREG | 0o755),
                                   ('Fenix.app/Contents/Resources/Fenix', '../MacOS/Fenix', stat.S_IFLNK | 0o777)])
        self.assertTrue((carpeta / 'Contents/Resources/Fenix').is_symlink())
        self.assertTrue(os.access(carpeta / 'Contents/MacOS/Fenix', os.X_OK))

    def test_tar_archivo_y_dispositivo_rechazado(self):
        paquete = self.raiz / 'paquete.tar.gz'
        salida = self.raiz / 'extraido'
        salida.mkdir()
        with tarfile.open(paquete, 'w:gz') as tar:
            info = tarfile.TarInfo('Fenix/Fenix')
            info.size, info.mode = 3, 0o755
            tar.addfile(info, io.BytesIO(b'ELF'))
        n.extraer(paquete, salida, 'linux-x64', self.cancelar, self.progreso)
        self.assertEqual((salida / 'Fenix/Fenix').read_bytes(), b'ELF')
        with tarfile.open(paquete, 'w:gz') as tar:
            info = tarfile.TarInfo('Fenix/device')
            info.type = tarfile.CHRTYPE
            tar.addfile(info)
        with self.assertRaises(RuntimeError):
            n.extraer(paquete, salida, 'linux-x64', self.cancelar, self.progreso)

    def test_cancelacion_y_espacio_extraccion(self):
        paquete = self.zip([('Fenix.app/file', b'dato', 0o644)])
        with patch.object(n.shutil, 'disk_usage', return_value=type('Disco', (), {'free': 0})()):
            with self.assertRaisesRegex(RuntimeError, 'espacio'):
                n.extraer(paquete, self.raiz, 'macos-arm64', self.cancelar, self.progreso)
        self.cancelar.set()
        with self.assertRaises(n.Cancelado):
            n.extraer(paquete, self.raiz, 'macos-arm64', self.cancelar, self.progreso)

    def preparar_reemplazo(self):
        nuevo, destino = self.raiz / 'nuevo', self.raiz / 'Fenix'
        nuevo.mkdir()
        destino.mkdir()
        (nuevo / 'version').write_text('nueva')
        (destino / 'version').write_text('anterior')
        return nuevo, destino

    def test_reemplazo_conserva_respaldo(self):
        nuevo, destino = self.preparar_reemplazo()
        respaldo = n.sustituir(nuevo, destino, lambda: None)
        self.assertEqual((destino / 'version').read_text(), 'nueva')
        self.assertEqual((respaldo / 'version').read_text(), 'anterior')

    def test_rollback_si_no_arranca(self):
        nuevo, destino = self.preparar_reemplazo()
        def fallo():
            raise RuntimeError('No arranca')
        with self.assertRaisesRegex(RuntimeError, 'No arranca'):
            n.sustituir(nuevo, destino, fallo)
        self.assertEqual((destino / 'version').read_text(), 'anterior')

    def test_rollback_si_falla_rename(self):
        nuevo, destino = self.preparar_reemplazo()
        original = Path.rename
        def rename(ruta, target):
            if ruta == nuevo:
                raise PermissionError('sin permiso')
            return original(ruta, target)
        with patch.object(Path, 'rename', rename), self.assertRaises(PermissionError):
            n.sustituir(nuevo, destino, lambda: None)
        self.assertEqual((destino / 'version').read_text(), 'anterior')

    def test_carpeta_ajena_no_se_sustituye(self):
        destino = self.raiz / 'Fenix'
        destino.mkdir()
        (destino / 'personal.txt').write_text('conservar')
        with self.assertRaises(RuntimeError):
            n.instalar(destino, 'linux-x64', self.cancelar, self.progreso)
        self.assertEqual((destino / 'personal.txt').read_text(), 'conservar')

    @unittest.skipIf(os.name == 'nt', 'Bloqueo POSIX.')
    def test_bloqueo_dos_instaladores(self):
        with n.bloqueo(self.raiz / 'Fenix'):
            with self.assertRaises(RuntimeError):
                with n.bloqueo(self.raiz / 'Fenix'):
                    pass

    def test_entorno_no_hereda_librerias_del_instalador(self):
        with patch.dict(os.environ, {'LD_LIBRARY_PATH': '/instalador', 'LD_LIBRARY_PATH_ORIG': '/original',
                                     'QT_PLUGIN_PATH': '/instalador/qt'}):
            env = n.entorno_externo()
        self.assertEqual(env['LD_LIBRARY_PATH'], '/original')
        self.assertNotIn('QT_PLUGIN_PATH', env)
        self.assertEqual(env['PYINSTALLER_RESET_ENVIRONMENT'], '1')

    def test_acceso_menu_linux_y_no_sobrescribe_ajeno(self):
        with patch.dict(os.environ, {'XDG_DATA_HOME': str(self.raiz)}):
            ruta = n.crear_acceso_linux(self.raiz / 'carpeta con espacios/Fenix')
            self.assertIn('Exec="', ruta.read_text(encoding='utf-8'))
            self.assertIn('X-Fenix-Installer=true', ruta.read_text(encoding='utf-8'))
            ruta.write_text('acceso de otra app')
            with self.assertRaises(RuntimeError):
                n.crear_acceso_linux(self.raiz / 'Fenix')

    def test_lanzador_linux_independiente(self):
        with patch.object(n.subprocess, 'Popen') as popen:
            popen.return_value.wait.side_effect = subprocess.TimeoutExpired('Fenix', 0.5)
            n.abrir_fenix(self.raiz / 'Fenix', 'linux-x64')
            self.assertTrue(popen.call_args.kwargs['start_new_session'])
            self.assertEqual(popen.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')


if __name__ == '__main__':
    unittest.main()
