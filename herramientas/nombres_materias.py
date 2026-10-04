"""Formato de presentación para sugerencias SIA, no para los datos originales."""
import re
import unicodedata


CONECTORES = frozenset(
    "a al ante bajo con contra de del desde durante e el en entre hacia hasta "
    "la las lo los o para por que sin sobre tras u un una unos unas y".split()
)
SIGLAS = frozenset(
    "CNT SIA UNAL TI TIC TICS IA CAD CAM CAE BIM SIG GIS GPS SQL UML HTML CSS "
    "XML ADN ARN UV NMR RMN HPLC MATLAB SPSS SAP ERP IoT".upper().split()
)
# Solo palabras académicas inequívocas. No adivinar tildes en términos ambiguos
# (p. ej. ingles/inglés, practico/práctico) ni usar reglas ortográficas generales.
TILDES = {
    "analisis": "análisis", "algebra": "álgebra", "calculo": "cálculo",
    "biologia": "biología", "quimica": "química", "quimico": "químico",
    "fisica": "física", "fisico": "físico", "estadistica": "estadística",
    "estadistico": "estadístico", "ingenieria": "ingeniería",
    "matematica": "matemática", "matematicas": "matemáticas",
    "mecanica": "mecánica", "mecanico": "mecánico", "electrica": "eléctrica",
    "electrico": "eléctrico", "electronica": "electrónica",
    "programacion": "programación", "introduccion": "introducción", "computacion": "computación",
    "administracion": "administración", "gestion": "gestión",
    "economia": "economía", "teoria": "teoría", "geometria": "geometría",
    "geologia": "geología", "ecologia": "ecología", "termodinamica": "termodinámica",
}
ROMANO = re.compile(r"M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
PALABRA = re.compile(r"[^\W_]+", re.UNICODE)


def sugerir_nombre_materia(nombre: str) -> str:
    """Mayúscula en palabras principales, conectores bajos, siglas conservadas."""
    texto = " ".join(unicodedata.normalize("NFC", nombre).split())
    primera = True

    def convertir(match):
        nonlocal primera
        palabra = match.group()
        minuscula, mayuscula = palabra.lower(), palabra.upper()
        inicial = primera
        if any(c.isalpha() for c in palabra):
            primera = False
        if minuscula in CONECTORES:
            return minuscula.capitalize() if inicial else minuscula
        if (mayuscula in SIGLAS or ROMANO.fullmatch(mayuscula)
                or re.fullmatch(r"[BCDFGHJKLMNPQRSTVWXYZ]{2,6}", mayuscula)
                or (any(c.isdigit() for c in palabra) and any(c.isalpha() for c in palabra))):
            return mayuscula
        # Conservar nombres técnicos de escritura mixta (p. ej. JavaScript).
        if not palabra.isupper() and not palabra.islower() and not palabra.istitle():
            return palabra
        return TILDES.get(minuscula, minuscula).capitalize()

    return PALABRA.sub(convertir, texto)
