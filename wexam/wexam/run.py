"""Lanzador de la aplicación web"""
from werkzeug.serving import run_simple
from .instance_app import instance_app


def run():
    """Instancia la app y pone en marcha el servidor de desarrollo"""
    app = instance_app()
    # Lanzar aplicación con werkzeug, con reloader
    print("Iniciando servidor...")
    run_simple('0.0.0.0', 5000, app, use_reloader=True, use_debugger=False)

if __name__ == '__main__':
    run()
