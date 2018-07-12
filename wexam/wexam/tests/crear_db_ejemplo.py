from pony.orm import *
from wexam import mixins
from wexam.model import *
import os.path
import os
from datetime import datetime
from passlib.hash import bcrypt
import random


def crear_db_ejemplo(db):
    # este script crea una base de datos de ejemplo, con contenidos medio aleatorios
    random.seed(1)  # Reproducible tests
    # Creamos un par de profesores (autores)
    with db_session():
        now = datetime.now()
        jose = Profesor(nombre="Jose Luis Díaz", email="jldiaz@uniovi.es",
                    username="jldiaz", role="profesor",
                    fecha_creacion=now, fecha_modificacion=now,
                    password=bcrypt.hash("0000"))
        marco = Profesor(nombre="Marco Antonio García", email="marco@uniovi.es",
                    username="marco", role="profesor",
                    fecha_creacion=now, fecha_modificacion=now,
                    password=bcrypt.hash("0000"))
        joaquin = Profesor(nombre="Joaquín Entrialgo", email="joaquin@uniovi.es",
                    username="joaquin", role="profesor",
                    fecha_creacion=now, fecha_modificacion=now,
                    password=bcrypt.hash("0000"))
        arias = Profesor(nombre="José Ramón Arias", email="arias@uniovi.es",
                    username="arias", role="profesor",
                    fecha_creacion=now, fecha_modificacion=now,
                    password=bcrypt.hash("0000"))
        javier = Profesor(nombre="Javier García", email="javier@uniovi.es",
                    username="javier", role="profesor",
                    fecha_creacion=now, fecha_modificacion=now,
                    password=bcrypt.hash("0000"))
        admin = Profesor(nombre="Administrador", email="admin@example.com",
                    username="admin", role="admin",
                    fecha_creacion=now, fecha_modificacion=now,
                    password=bcrypt.hash("0000"))
        # jldiaz crea un par de círculos y mete en ellos a otros profesores
        now = datetime.now()
        c_sd = Circulo(nombre="Sist. Dist.", creador=jose,
                       fecha_creacion=now, fecha_modificacion=now)
        c_sd.miembros.add([marco, joaquin])

        now = datetime.now()
        c_fc = Circulo(nombre="Fund. Comput.", creador=jose,
                       fecha_creacion=now, fecha_modificacion=now)
        c_fc.miembros.add([joaquin, arias])

        commit()  # Habrá una excepción si ya estaban en la base de datos, pues el email debe ser único


    # Ahora creamos varios problemas de ejemplo
    with db_session():
        now = datetime.now()
        # creemos unos tags
        tags = [Tag(name=t) for t in ["sd", "sockets", "is", "asd"]]

        # Vamos a crear ahora un examen de ejemplo, con 4 problemas
        # cada problema recibe un tag aleatorio y un número de cuestiones
        # aleatorias entre 3 y 5
        autores = list(Profesor.select()) # Todos los autores antes creados
        secuencia_autores=[0,0,0,0,1,1,2,3,3,4]
        for n in range(len(secuencia_autores)):
            problema = Problema(
                resumen = "Problema %s" % n,
                enunciado = "Enunciado general del problema %s" % n,
                tags = [tags[i] for i in range(random.randint(1,4))],
                creador = autores[secuencia_autores[n]],
                fecha_creacion=now, fecha_modificacion=now,
                )
            preguntas = [Cuestion(
                enunciado = "Enunciado de la pregunta %s del problema %s" % (i, n),
                respuesta = "Respuesta de la pregunta %s del problema %s" % (i, n),
                puntos = random.randint(1,2),
                problema = problema,
                posicion = i,
            ) for i in range(random.randint(3,5))]

        commit()

    # Ahora compartimos los tres problemas 0-3 con el círculo SD y los
    # problemas 2-3 con el circulo FC. Observa que el problema 2 está compartido
    # con ambos círculos
    with db_session():
        problemas = list(Problema.select())
        circulos = list(Circulo.select())
        circulos[0].problemas_visibles.add(problemas[0:3])
        circulos[1].problemas_visibles.add(problemas[2:4])
        commit()

    # Finalmente creamos un par de examenes, uno abierto, otro cerrado, tomando problemas al azar
    with db_session():
        now = datetime.now()
        problemas = list(Problema.select()) # Estos son los problemas donde elegir
        autores = list(Profesor.select()) # Todos los autores antes creados
        elegidos = random.sample(problemas, random.randint(3,6))
        asignatura = Asignatura(nombre="Sistemas Distribuidos", titulacion="Informática")
        examen1 = Examen(asignatura = asignatura,
                        fecha = datetime.today(),
                        convocatoria = "Extraordinaria de Mayo",
                        intro = "Este examen, blah, blah",
                        tipo = random.choice('ABCD'),
                        creador = random.choice(autores),
                        fecha_creacion=now, fecha_modificacion=now,
        )
        examen1.problemas = [Problema_examen(posicion=n, problema_id=p, examen_id=examen1) for n,p in enumerate(elegidos)]
        n_preg = examen1.problemas.count()
        total_puntos = sum(q.puntos for p in examen1.problemas for q in p.problema_id.cuestiones)
        examen1.intro = """
        Este examen tiene %d preguntas que suman un total de %d puntos, por lo que cada 
        pregunta tiene un valor de %f.
        """ % (n_preg, total_puntos, 10/total_puntos)

        elegidos = random.sample(problemas[1:], random.randint(3,6))
        examen1 = Examen( asignatura = asignatura,
                        fecha = datetime.today(),
                        convocatoria = "Extraordinaria de Junio",
                        intro = "Este examen, blah, blah",
                        tipo = random.choice('ABCD'),
                        creador = random.choice(autores),
                        estado = "cerrado",
                        fecha_creacion=now, fecha_modificacion=now,
        )
        examen1.problemas = [Problema_examen(posicion=n, problema_id=p, examen_id=examen1) for n,p in enumerate(elegidos)]
        n_preg = examen1.problemas.count()
        total_puntos = sum(q.puntos for p in examen1.problemas for q in p.problema_id.cuestiones)
        examen1.intro = """
        Este examen tiene %d preguntas que suman un total de %d puntos, por lo que cada 
        pregunta tiene un valor de %f.
        """ % (n_preg, total_puntos, 10/total_puntos)


if __name__ == "__main__":
    fname = "database.sqlite"
    if os.path.isfile(fname):
        s = input("%s ya existe. Borrarlo? (S/N) " % fname)
        if s.upper() == "S":
            print("Borrando y re-creando base de datos")
            os.remove(fname)
        else:
            print("No se borra, intentando añadir")

    db.bind('sqlite', fname, create_db=True)
    db.generate_mapping(create_tables=True)
    crear_db_ejemplo(db)