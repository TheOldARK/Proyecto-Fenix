"""Ventana del instalador descargable; nunca incluye Chromium ni Fénix completo."""
import argparse
import json
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QThread, Signal, QTimer, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QHBoxLayout,
                              QLabel, QLineEdit, QMessageBox, QProgressBar,
                              QPushButton, QVBoxLayout, QWidget)

from herramientas.instalacion_nativa import (Cancelado, abrir_fenix, destino_predeterminado,
                                            instalar, nombre_raiz, plataforma_nativa)


class Trabajador(QThread):
    progreso = Signal(str, int, bool)
    resultado = Signal(object)

    def __init__(self, destino, sistema, acceso, abrir, parent=None):
        super().__init__(parent)
        self.destino, self.sistema, self.acceso, self.abrir = destino, sistema, acceso, abrir
        self.cancelar = threading.Event()

    def run(self):
        try:
            resultado = instalar(self.destino, self.sistema, self.cancelar, self.progreso.emit, self.acceso)
            if self.abrir:
                self.progreso.emit('Abriendo Fénix…', 100, False)
                try:
                    abrir_fenix(resultado['destino'], self.sistema)
                except Exception as error:
                    resultado['advertencias'].append(f'La instalación terminó, pero no se pudo abrir Fénix: {error}')
            self.resultado.emit({'correcto': True, **resultado})
        except Cancelado as error:
            self.resultado.emit({'correcto': False, 'cancelado': True, 'error': str(error)})
        except Exception as error:
            self.resultado.emit({'correcto': False, 'error': str(error)})


class Instalador(QWidget):
    def __init__(self, prueba=None, informe=None):
        super().__init__()
        self.sistema = plataforma_nativa()
        self.prueba, self.informe = prueba, informe
        self.trabajador = None
        self.resultado = None
        self.cancelable = True
        self.setWindowTitle('Instalar Fénix')
        self.setMinimumSize(610, 425)
        self.resize(650, 460)
        recursos = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'recursos'
        self.setWindowIcon(QIcon(str(recursos / 'logo.png')))
        self.setStyleSheet('''
            QWidget { background: #181818; color: #f2f2f2; font-size: 14px; }
            QLineEdit { background: #252525; border: 1px solid #666; border-radius: 5px; padding: 8px; }
            QPushButton { background: #303030; border: 1px solid #666; border-radius: 5px; padding: 9px 16px; }
            QPushButton:hover { border-color: #43ce83; }
            QPushButton:disabled { color: #888; }
            QProgressBar { border: 1px solid #666; border-radius: 5px; min-height: 22px; text-align: center; color: white; }
            QProgressBar::chunk { background: #20744b; }
            QCheckBox { spacing: 8px; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        cabecera = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(str(recursos / 'logo.png')).scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        cabecera.addWidget(logo)
        titulo = QLabel('Instalar Fénix')
        titulo.setStyleSheet('font-size: 24px; font-weight: bold;')
        cabecera.addWidget(titulo, 1)
        layout.addLayout(cabecera)
        descripcion = QLabel(f'Descargará la versión estable más reciente para {self.sistema}.\nNo necesitas instalar Python.')
        descripcion.setWordWrap(True)
        layout.addWidget(descripcion)
        layout.addWidget(QLabel('Carpeta de instalación:'))
        fila = QHBoxLayout()
        self.ruta = QLineEdit(str(prueba or destino_predeterminado(self.sistema)))
        self.ruta.setReadOnly(True)
        fila.addWidget(self.ruta, 1)
        self.examinar = QPushButton('Elegir…')
        self.examinar.clicked.connect(self._elegir)
        fila.addWidget(self.examinar)
        layout.addLayout(fila)
        self.acceso = QCheckBox('Añadir Fénix al menú de aplicaciones')
        self.acceso.setChecked(True)
        self.acceso.setVisible(self.sistema == 'linux-x64')
        layout.addWidget(self.acceso)
        self.abrir = QCheckBox('Abrir Fénix al terminar y cerrar este instalador')
        self.abrir.setChecked(not bool(prueba))
        layout.addWidget(self.abrir)
        self.barra = QProgressBar()
        self.barra.setValue(0)
        layout.addWidget(self.barra)
        self.estado = QLabel('Se comprobará la descarga antes de instalar. Cierra Fénix si ya lo tienes abierto.')
        self.estado.setWordWrap(True)
        self.estado.setMinimumHeight(65)
        layout.addWidget(self.estado)
        layout.addStretch()
        botones = QHBoxLayout()
        botones.addStretch()
        self.boton_instalar = QPushButton('Instalar')
        self.boton_instalar.clicked.connect(self._iniciar)
        botones.addWidget(self.boton_instalar)
        self.boton_cancelar = QPushButton('Cerrar')
        self.boton_cancelar.clicked.connect(self.close)
        botones.addWidget(self.boton_cancelar)
        layout.addLayout(botones)
        if prueba:
            QTimer.singleShot(200, self._iniciar)

    def _elegir(self):
        carpeta = QFileDialog.getExistingDirectory(self, 'Carpeta donde guardar Fénix', str(Path(self.ruta.text()).parent))
        if carpeta:
            self.ruta.setText(str(Path(carpeta) / nombre_raiz(self.sistema)))

    def _iniciar(self):
        destino = Path(self.ruta.text())
        if destino.exists() and not self.prueba:
            respuesta = QMessageBox.question(self, 'Fénix ya está instalado',
                '¿Instalar la versión más reciente en esta carpeta?\n'
                'Cierra Fénix antes de continuar. Se conservará un respaldo de la aplicación anterior; tu perfil no se modifica.')
            if respuesta != QMessageBox.Yes:
                return
        self.resultado = None
        self.cancelable = True
        for control in (self.examinar, self.boton_instalar, self.acceso, self.abrir):
            control.setEnabled(False)
        self.boton_cancelar.setText('Cancelar')
        self.trabajador = Trabajador(destino, self.sistema, self.acceso.isChecked() and not bool(self.prueba),
                                    self.abrir.isChecked(), self)
        self.trabajador.progreso.connect(self._progreso)
        self.trabajador.resultado.connect(self._resultado)
        self.trabajador.finished.connect(self._finalizar)
        self.trabajador.start()

    def _progreso(self, texto, porcentaje, cancelable):
        self.estado.setText(texto)
        self.cancelable = cancelable
        self.boton_cancelar.setEnabled(cancelable)
        self.barra.setRange(0, 0 if porcentaje in (0, 82, 88) else 100)
        if self.barra.maximum():
            self.barra.setValue(porcentaje)

    def _resultado(self, resultado):
        self.resultado = resultado

    def _finalizar(self):
        self.trabajador.deleteLater()
        self.trabajador = None  # Ya terminó: es seguro cerrar QApplication.
        resultado = self.resultado or {'correcto': False, 'error': 'El instalador terminó sin resultado.'}
        self.boton_cancelar.setEnabled(True)
        self.boton_cancelar.setText('Cerrar')
        self.barra.setRange(0, 100)
        self.barra.setValue(100 if resultado['correcto'] else 0)
        if resultado['correcto']:
            texto = f"Fénix {resultado['version']} instalado en:\n{resultado['destino']}"
            if resultado.get('respaldo'):
                texto += '\nRespaldo anterior: ' + resultado['respaldo']
            self.estado.setText(texto)
        else:
            self.estado.setText(resultado['error'])
            for control in (self.examinar, self.boton_instalar, self.acceso, self.abrir):
                control.setEnabled(True)
        if self.prueba:
            if self.informe:
                ruta = Path(self.informe)
                ruta.parent.mkdir(parents=True, exist_ok=True)
                ruta.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding='utf-8')
                self.grab().save(str(ruta.with_suffix('.png')))
            QTimer.singleShot(100, lambda: QApplication.exit(0 if resultado['correcto'] else 1))
        elif resultado.get('advertencias'):
            QMessageBox.warning(self, 'Fénix instalado', '\n'.join(resultado['advertencias']))
        elif resultado['correcto'] and self.abrir.isChecked():
            self.close()
        elif not resultado['correcto'] and not resultado.get('cancelado'):
            QMessageBox.critical(self, 'No se pudo instalar Fénix', resultado['error'])

    def closeEvent(self, evento):
        if self.trabajador is not None:
            evento.ignore()
            if self.cancelable:
                self.trabajador.cancelar.set()
                self.estado.setText('Cancelando de forma segura; esperando que termine la operación actual…')
                self.boton_cancelar.setEnabled(False)
            return
        evento.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prueba-instalar', help='Prueba automatizada en una carpeta explícita; no abre Fénix ni crea accesos.')
    parser.add_argument('--informe')
    args = parser.parse_args()
    app = QApplication([])
    ventana = Instalador(args.prueba_instalar, args.informe)
    ventana.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
