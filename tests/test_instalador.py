import hashlib
import json
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from zipfile import ZipFile
from servicios import instalador as i
from servicios import actualizacion_aplicacion as a

DAT = '_internal/playwright/driver/package/.local-browsers/chromium_headless_shell-1243/chrome-headless-shell-win64/PrivacySandboxAttestationsPreloaded/privacy-sandbox-attestations.dat'


class InstaladorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='fx-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.zip = self.base / 'paquete.zip'
        self.old = self.base / 'Fenix'
        self.old.mkdir()
        (self.old / 'Fenix.exe').write_bytes(b'original')
        self.new = self.base / 'nuevo'
        self.crear_zip()

    def crear_zip(self, extra=None):
        archivos = {'Fenix.exe': b'nuevo', 'updater/FenixUpdater.exe': b'helper', DAT: b'atestaciones'}
        self.manifiesto = {'schema': 1, 'version': '1.0.8.1', 'files': {
            n: {'size': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for n, b in archivos.items()}}
        with ZipFile(self.zip, 'w') as z:
            for n, b in archivos.items():
                z.writestr('Fenix/' + n, b)
            z.writestr('Fenix/' + i.MANIFIESTO, json.dumps(self.manifiesto))
            if extra:
                z.writestr(extra, b'x')

    def test_ruta_mayor_300(self):
        destino = self.base / ('nombre largo ' * 7).strip() / ('segundo ' * 7).strip()
        i.ruta_larga(destino.parent).mkdir(parents=True)
        self.assertGreater(len(str(destino / DAT)), 300)
        i.extraer_verificado(self.zip, destino, self.old)
        self.assertEqual(i.ruta_larga(destino / DAT).read_bytes(), b'atestaciones')

    def test_rutas_peligrosas_y_duplicadas(self):
        for n in ('../fuera', 'Fenix/../fuera', 'C:/fuera', 'Fenix/a:ads', 'Fenix/CON', 'Fenix/FENIX.exe'):
            self.crear_zip(n)
            with ZipFile(self.zip) as z, self.assertRaises(ValueError):
                i.leer_paquete(z)

    def test_detecta_archivo_ausente(self):
        i.extraer_verificado(self.zip, self.new, self.old)
        (self.new / DAT).unlink()
        with self.assertRaises(ValueError):
            i.verificar_instalacion(self.new, self.manifiesto)

    def test_detecta_bytes_modificados(self):
        i.extraer_verificado(self.zip, self.new, self.old)
        (self.new / 'Fenix.exe').write_bytes(b'otros')
        with self.assertRaises(ValueError):
            i.verificar_instalacion(self.new, self.manifiesto)

    def test_zip_sin_dat_se_rechaza_antes_de_instalar(self):
        incompleto = self.base / 'incompleto.zip'
        with ZipFile(self.zip) as origen, ZipFile(incompleto, 'w') as destino:
            for info in origen.infolist():
                if not info.filename.endswith('privacy-sandbox-attestations.dat'):
                    destino.writestr(info, origen.read(info))
        with ZipFile(incompleto) as z, self.assertRaisesRegex(ValueError, 'Paquete incompleto'):
            i.leer_paquete(z)
        self.assertEqual((self.old / 'Fenix.exe').read_bytes(), b'original')

    def recuperar(self, contenido):
        origen = self.old / DAT
        origen.parent.mkdir(parents=True)
        origen.write_bytes(contenido)
        abrir = ZipFile.open
        def fallo(z, miembro, *args, **kwargs):
            if getattr(miembro, 'filename', '') == 'Fenix/' + DAT:
                raise OSError('Fallo de lectura simulado')
            return abrir(z, miembro, *args, **kwargs)
        with patch.object(ZipFile, 'open', fallo), patch.object(i.time, 'sleep'):
            return i.extraer_verificado(self.zip, self.new, self.old)

    def test_recupera_original_identico(self):
        self.recuperar(b'atestaciones')
        self.assertEqual((self.new / DAT).read_bytes(), b'atestaciones')

    def test_rechaza_original_incompatible(self):
        with self.assertRaises(OSError):
            self.recuperar(b'distinto')

    def job(self):
        return {'instalacion': str(self.old), 'paquete': str(self.zip), 'pid': 999999,
                'ready': str(self.base / 'ready.json'), 'resultado': str(self.base / 'resultado.json')}

    def test_rollback_si_diagnostico_falla(self):
        with patch.object(i, 'esperar_cierre'), patch.object(i, 'diagnosticar', side_effect=RuntimeError('fallo Qt')):
            self.assertEqual(i.instalar(self.job()), 1)
        self.assertEqual((self.old / 'Fenix.exe').read_bytes(), b'original')

    def test_original_intacto_sin_espacio(self):
        with patch.object(i, 'esperar_cierre'), patch.object(i.shutil, 'disk_usage', return_value=Mock(free=0)):
            self.assertEqual(i.instalar(self.job()), 1)
        self.assertEqual((self.old / 'Fenix.exe').read_bytes(), b'original')

    def test_rollback_si_no_arranca_interfaz(self):
        with patch.object(i, 'esperar_cierre'), patch.object(i, 'diagnosticar'), patch.object(i.subprocess, 'Popen', side_effect=OSError('No inicia')):
            self.assertEqual(i.instalar(self.job()), 1)
        self.assertEqual((self.old / 'Fenix.exe').read_bytes(), b'original')

    def test_actualiza_y_reintenta_sin_bloqueo_obsoleto(self):
        with patch.object(i, 'esperar_cierre'), patch.object(i, 'diagnosticar'), patch.object(i.subprocess, 'Popen', return_value=Mock(pid=123)):
            self.assertEqual(i.instalar(self.job()), 0)
            self.assertEqual(i.instalar(self.job()), 0)
        self.assertEqual((self.old / 'Fenix.exe').read_bytes(), b'nuevo')

    def test_recupera_intercambio_interrumpido(self):
        ident = hashlib.sha256(str(self.old.resolve()).casefold().encode()).hexdigest()[:12]
        trabajo = self.old.parent / ('.fx-' + ident)
        trabajo.mkdir()
        self.old.rename(trabajo / 'anterior')
        i.guardar(trabajo / 'estado.json', {'fase': 'intercambiando'})
        with patch.object(i, 'esperar_cierre'), patch.object(i, 'extraer_verificado', side_effect=ValueError('ZIP roto')):
            self.assertEqual(i.instalar(self.job()), 1)
        self.assertEqual((self.old / 'Fenix.exe').read_bytes(), b'original')

    def test_versiones(self):
        self.assertGreater(a._version('1.0.8.1'), a._version('1.0.8'))
        self.assertGreater(a._version('1.0.8'), a._version('1.0.7b'))
        self.assertEqual(a._version('1.0.8'), a._version('1.0.8.0'))

    @unittest.skipUnless(os.name == 'nt', 'Bloqueo nativo de Windows')
    def test_bloqueo_concurrente_no_toca_instalacion(self):
        import msvcrt
        ident = hashlib.sha256(str(self.old.resolve()).casefold().encode()).hexdigest()[:12]
        trabajo = self.old.parent / ('.fx-' + ident)
        trabajo.mkdir()
        with (trabajo / 'lock').open('w+b') as lock:
            lock.write(b'0')
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                self.assertEqual(i.instalar(self.job()), 1)
                self.assertFalse(Path(self.job()['ready']).exists())
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        self.assertEqual((self.old / 'Fenix.exe').read_bytes(), b'original')

    def test_descarga_rechaza_tamano_hash_version_y_zip_roto(self):
        contenido = self.zip.read_bytes()
        base = {'version': '1.0.8.1', 'url': 'https://example.com/paquete'}
        for cambios, cuerpo in [({'tamano': 1}, contenido), ({'sha256': '0'*64}, contenido),
                                 ({'version': '1.0.9'}, contenido), ({}, b'no es zip')]:
            with patch.object(a, 'urlopen', return_value=io.BytesIO(cuerpo)):
                with self.assertRaises(Exception):
                    a.descargar_release(base | cambios, self.base / 'descargado.zip')
            self.assertFalse((self.base / 'descargado.zip').exists())

    def test_release_mayor_no_primera(self):
        releases = [{'tag_name': 'v'+v, 'assets': [{'name': f'Fenix-{v}-windows-x64.zip', 'browser_download_url': 'https://example.com/a'}]} for v in ('1.0.7', '1.0.8.1', '1.0.8')]
        with patch.object(a, 'urlopen', return_value=io.BytesIO(json.dumps(releases).encode())), \
             patch.object(a, 'nombre_paquete', side_effect=lambda v: f'Fenix-{v}-windows-x64.zip'):
            self.assertEqual(a.consultar_ultima_version()['version'], '1.0.8.1')


if __name__ == '__main__':
    unittest.main()
