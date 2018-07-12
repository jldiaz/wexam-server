"""Para implementar una herramienta de línea de comandos que permita consultar las
diferentes rutas expuestas por la API de la app.

El script de instalación `setup.py` instala el comando `morepathq` que usa este
módulo, y puede usarse por ejemplo así:

    $ morepathq path

para ver todas las rutas "de alto nivel", o bien:

    $ morepathq view

para ver todas las vistas y qué función maneja cada una.
"""
import json
import dectate
import morepath
from .app import App

def query_tool():
    """Usa dectate.query_tool() para consultar las rutas de la API."""
    morepath.autoscan()
    # Cargamos la configuración de la aplicación
    with open('settings.json') as config:
        settings_dict = json.load(config)
    App.init_settings(settings_dict)
    morepath.commit(App)
    dectate.query_tool(App.commit())
