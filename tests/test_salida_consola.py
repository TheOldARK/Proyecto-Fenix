import io
import unittest
from unittest.mock import patch

import main


class SalidaConsolaTests(unittest.TestCase):
    def test_unicode_no_representable_no_aborta_el_worker(self):
        salida_binaria = io.BytesIO()
        error_binario = io.BytesIO()
        salida = io.TextIOWrapper(salida_binaria, encoding="cp1252")
        error = io.TextIOWrapper(error_binario, encoding="cp1252")

        with patch.object(main.sys, "stdout", salida), patch.object(main.sys, "stderr", error):
            main.configurar_salida_consola_segura()
            print("⚠ aviso", file=salida)
            salida.flush()

        self.assertIn(b"\\u26a0 aviso", salida_binaria.getvalue())
        salida.detach()
        error.detach()


if __name__ == "__main__":
    unittest.main()
