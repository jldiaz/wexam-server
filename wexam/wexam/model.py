"""Modelo de la base de datos, para Pony ORM"""

from datetime import datetime
from pony.orm import (Database, PrimaryKey, composite_index, Required, Optional, Set)
#                      LongUnicode, unicode)
import simhash
from . import mixins

# pylint: disable=invalid-name,missing-docstring,too-few-public-methods

db = Database()

# Cada modelo es extendido a través de un Mixin, que implementa funciones
# para hacer un update parcial del modelo, o un delete, verificando que se
# cumplan ciertos requisitos, dependientes de cada modelo

class Examen(db.Entity, mixins.ExamenMixin):
    id = PrimaryKey(int, auto=True)
    estado = Required(str, default='abierto')
    asignatura = Required('Asignatura')
    fecha = Required(datetime)
    convocatoria = Required(str)
    intro = Optional(str)
    tipo = Required(str, 1)
    problemas = Set('Problema_examen', cascade_delete=True)
                # Nota: el cascade_delete no implica que se borrarán los problemas al borrar el examen
                # sino que se borrarán sus asociaciones en la tabla Problema_examen
    creador = Required('Profesor')
    publicado = Optional(datetime)
    fecha_creacion = Required(datetime)
    fecha_modificacion = Required(datetime)


class Asignatura(db.Entity, mixins.AsignaturaMixin):
    id = PrimaryKey(int, auto=True)
    nombre = Required(str)
    titulacion = Required(str)
    composite_index(nombre, titulacion)
    examenes = Set(Examen)


class Problema(db.Entity, mixins.ProblemaMixin):
    id = PrimaryKey(int, auto=True)
    resumen = Optional(str)
    enunciado = Optional(str)
    metainfos = Set('Metainfo')
    problema_origen = Optional('Problema', reverse='problemas_derivados')
    problemas_derivados = Set('Problema', reverse='problema_origen')
    cuestiones = Set('Cuestion')
    figuras = Set('Figura')
    tags = Set('Tag')
    creador = Required('Profesor')
    compartido_con = Set('Circulo')
    examenes = Set('Problema_examen')
    fecha_creacion = Required(datetime)
    fecha_modificacion = Required(datetime)
    simhash = Required(str, default="simhash")


    def compute_simhash(self):
        texto = []
        texto.append(self.enunciado)
        for p in self.cuestiones:
            texto.append(p.enunciado)
            texto.append(p.respuesta)
        self.simhash = "%x" % simhash.Simhash("\n".join(texto)).value

    def before_insert(self):
        """Antes de insertar el problema, computemos su simhash"""
        self.compute_simhash()

    def before_update(self):
        """Antes de actualizar el problema, recomputar su simhash"""
        self.compute_simhash()


class Problema_examen(db.Entity):
    posicion = Required(int)
    problema_id = Required(Problema)
    examen_id = Required(Examen)
    PrimaryKey(problema_id, examen_id)


class Cuestion(db.Entity, mixins.UpdatableMixin):
    id = PrimaryKey(int, auto=True)
    enunciado = Required(str)
    respuesta = Required(str)
    explicacion = Optional(str)
    puntos = Required(float, default=1)
    problema = Required(Problema)
    posicion = Required(int)


class Figura(db.Entity):
    id = PrimaryKey(int, auto=True)
    filename = Required(str)
    problemas = Set(Problema)


class Tag(db.Entity):
    id = PrimaryKey(int, auto=True)
    name = Required(str)
    problemas = Set(Problema)


class Profesor(db.Entity, mixins.ProfesorMixin):
    id = PrimaryKey(int, auto=True)
    nombre = Required(str)
    email = Required(str, unique=True)
    username = Optional(str)
    password = Required(str)
    role = Required(str)
    problemas_creados = Set(Problema)
    examenes_creados = Set(Examen)
    circulos_en_que_esta = Set('Circulo', reverse='miembros')
    circulos_creados = Set('Circulo', reverse='creador')
    fecha_creacion = Required(datetime)
    fecha_modificacion = Required(datetime)
    tareas = Set('Tarea')


class Circulo(db.Entity, mixins.CirculoMixin):
    id = PrimaryKey(int, auto=True)
    nombre = Required(str)
    creador = Required(Profesor, reverse='circulos_creados')
    miembros = Set(Profesor, reverse='circulos_en_que_esta')
    problemas_visibles = Set(Problema)
    fecha_creacion = Required(datetime)
    fecha_modificacion = Required(datetime)


class Metainfo(db.Entity):
    id = PrimaryKey(int, auto=True)
    info = Required(str)
    problema = Required(Problema)


class Tarea(db.Entity, mixins.TareaMixin):
    id = PrimaryKey(str)
    nombre = Required(str)
    tipo = Required(str)
    creador = Required(Profesor, reverse='tareas')
    completada = Required(bool, default=False)