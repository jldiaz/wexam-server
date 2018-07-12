"Declara la aplicación"
from more.pony import PonyApp


class App(PonyApp):
    """La clase aplicación requerida por morepath, que hereda
    de PonyApp para que use las sesiones del ORM Pony en forma
    correcta (abre una sesión al recibir cada petición y la
    cierra al devolver la respuesta)"""
    pass
