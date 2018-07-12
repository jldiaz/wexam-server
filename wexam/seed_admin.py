import os.path
import os
from datetime import datetime
from passlib.hash import bcrypt

from pony.orm import db_session, commit
from wexam.instance_app import instance_app
from wexam.model import Profesor, db

def crear_admin_user(name, email, password):
    with db_session():
        now = datetime.now()
        admin = Profesor(nombre=name, email=email,
                    username="admin", role="admin",
                    fecha_creacion=now, fecha_modificacion=now,
                    password=bcrypt.hash(password))
        commit()


if __name__ == "__main__":
    app = instance_app()
    name = os.getenv("WEXAM_ADMIN_NAME", "Admin")
    email = os.getenv("WEXAM_ADMIN_EMAIL")
    password = os.getenv("WEXAM_ADMIN_PASSWORD")
    if email is None or password is None:
        print("Debes fijar las variables de entorno WEXAM_ADMIN_EMAIL y WEXAM_ADMIN_PASSWORD")
        exit()
    crear_admin_user(name, email, password)
