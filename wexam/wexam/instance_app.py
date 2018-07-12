# import logging
import json
import os
from urllib.parse import urlparse

import yaml
import morepath
import redis
import rq

from .app import App
from . import mixins
from .model import db


def setup_db(app):
    """Conecta con la base de datos de la aplicación"""
    if app.settings.database.provider == "from_database_url":
        url = os.getenv("DATABASE_URL", None)
        assert url is not None, "No existe la variable de entorno DATABASE_URL"
        data = urlparse(url)
        db_params = {
            "provider": data.scheme,
            "user": data.username,
            "password": data.password,
            "host": data.hostname,
            "port": data.port,
            "database": data.path[1:],
            "create_db": None
        }
    else:
        db_params = app.settings.database.__dict__.copy()
    print("Using database {}".format(db_params))
    db.bind(**db_params)
    db.generate_mapping(create_tables=True)

def setup_redis(app):
    """Intenta conectar con redis, o guarda None en las variables apropiadas para indicar
    que no está disponible"""
    if getattr(app.settings, "redis", None) is None:
        app.redis = None
        app.task_queue = None
    else:
        try:
            app.redis = redis.Redis.from_url(app.settings.redis.url, socket_timeout=10)
            app.task_queue = rq.Queue('json2latex-task', connection=app.redis)
        except:
            app.redis = None
            app.task_queue = None

def instance_app():
    """Crea una instancia de la aplicación"""

    morepath.autoscan()

    # Lo siguiente prepara el logger de pony.orm para que emita a un
    # fichero todas las sentencias SQL que va enviando a la base de datos
    # pony.orm.sql_debug(True)
    # logger = logging.getLogger("pony.orm.sql")
    # logger.setLevel(logging.INFO)
    # channel = logging.FileHandler("/tmp/sql_commands.log")
    # channel.setLevel(logging.INFO)
    # logger.addHandler(channel)

    # Hay que añadirle un handler a logging.root porque (según he visto
    # en el código de pony) sql_log() comprueba que haya uno, y si no lo
    # hay emite las cosas por la salida estándar haciendo caso omiso de la
    # configuración de log. Pero como no me interesa que el logger raiz
    # haga nada, le asigno el handler nulo
    # logging.root.addHandler(logging.NullHandler())

    env = os.getenv("RUN_ENV", "default")
    filename = "settings/{}.yaml".format(env)
    if not os.path.isfile(filename):
        filename = "settings/default.yaml"

    print("Usando configuración {}".format(filename))
    # Cargamos la configuración de la aplicación
    with open(filename) as config:
        settings_dict = yaml.load(config)
    App.init_settings(settings_dict)
    # morepath.commit(App)
    App.commit()

    app = App()

    setup_redis(app)
    setup_db(app)
    return app
