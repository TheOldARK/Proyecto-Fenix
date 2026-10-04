import unittest

from herramientas.nombres_materias import sugerir_nombre_materia


class NombresMateriasTests(unittest.TestCase):
    def test_ejemplo_y_conectores(self):
        for original, esperado in (
            ("ANALISIS ESTRUCTURAL I - CNT", "Análisis Estructural I - CNT"),
            ("INTRODUCCION A LA TEORIA DE LA COMPUTACION", "Introducción a la Teoría de la Computación"),
            ("FÍSICA DE ELECTRICIDAD Y MAGNETISMO", "Física de Electricidad y Magnetismo"),
            ("EL ARTE Y LA HISTORIA DEL SIGLO XXI", "El Arte y la Historia del Siglo XXI"),
            ("INGENIERIA CIVIL II", "Ingeniería Civil II"),
            ("BASES DE DATOS (SQL) - CNT", "Bases de Datos (SQL) - CNT"),
            ("  TEORÍA   DE\nLA  COMPUTACIÓN ", "Teoría de la Computación"),
            ("Programación con JavaScript", "Programación con JavaScript"),
            ("QUÍMICA FÍSICO-QUÍMICA IV", "Química Físico-Química IV"),
            ("INGLÉS INTENSIVO B2", "Inglés Intensivo B2"),
            ("", ""),
        ):
            with self.subTest(original=original):
                self.assertEqual(sugerir_nombre_materia(original), esperado)
                self.assertEqual(sugerir_nombre_materia(esperado), esperado)
