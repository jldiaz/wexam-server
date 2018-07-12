"""Clases para manejar colecciones de entidades (Problemas, Tags, etc.)

Manejan la extracción de la base de datos de las listas de entidades que
cumplan ciertos requisitos, y la creación de elementos nuevos que puedan
ser añadidos a cualquiera de esas listas.
"""
from datetime import datetime
from time import mktime, strptime
from pony.orm.core import ObjectNotFound
from pony.orm import commit
from pony.orm import desc
from passlib.hash import bcrypt

# from pony.orm import delete
from . import model
from . import util

# Colecciones de items de la base de datos
class DBCollection(object):
    """Colección genérica, que sirve para recuperar todos los objetos
    de un tipo (tabla) de la base de datos, añadir objetos nuevos, o
    modificar o borrar uno existente.

    La clase es muy genérica y vale para cualquier tabla, pero no hace
    validación ninguna de los datos que recibe, salvo la que haga la
    propia base de datos (la cual puede ser suficiente en ocasiones).

    No deberían instanciarse directamente objetos de esta clase, sino
    hacer clases derivadas y sobrecargar su método __init__ para que
    llamen al de esta clase, pasándole como parámetro la clase derivada.

    Si se necesitan comprobaciones más detalladas o transformaciones de
    los datos antes de guardarse en la base de datos, deben implementarse
    en una clase derivada de ésta (véase por ejemplo Profesores)
    """
    def __init__(self, clase, extra_parameters=None):
        """clase es el tipo de objetos que se almacena en esta colección"""
        self.clase = clase
        self.extra_parameters = extra_parameters

    def delete_object(self, id_):
        "Borra el objeto cuyo id se suministra"
        try:
            self.clase[id_].delete()
            return True
        except ObjectNotFound:
            return None

    def query(self):
        """Obtiene una lista de objetos, siendo posible filtrarlos
        mediante parámetros extra (sin usar aún)"""
        # Si no hay parámetros extra, simplemente retornar todos los objetos
        # de la tabla
        return list(self.clase.select())

    def get_created_by_user(self, id_):
        """Obtiene la lista de entidades de esta clase que han sido creadas
        por el usuario cuyo id se suministra. No funcionará correctamente
        si la clase no tiene campo 'creador'"""

        quien = model.Profesor.get(id=id_)
        if quien.role == "admin":
            return self.clase.select().order_by(desc(self.clase.fecha_modificacion))
        creados = (self.clase.select(lambda p: p.creador == quien)
                   .order_by(desc(self.clase.fecha_modificacion)))
        print(creados)
        return creados

    def add(self, data, tipo):
        """Añade un nuevo elemento del tipo 'tipo' a la colección. El parámetro
        'data' es un diccionario python con los nombres y valores de los
        campos del objeto a crear. No se validan"""
        self.check_type(tipo)
        data.update(fecha_creacion=datetime.now(), fecha_modificacion=datetime.now())
        nuevo = tipo(**data)
        commit()
        return nuevo

    def check_type(self, tipo):
        """Verifica que el tipo especificado en 'tipo' coincide con la clase
        a que pertenece el objeto 'self'"""
        if tipo != self.clase:
            raise TypeError("Intento de añadir un elemento %r a una "
                            "lista que almacena sólo %r" % (tipo, self.clase))


class Profesores(DBCollection):
    """Listado de profesores"""

    def __init__(self, extra_parameters=None):
        DBCollection.__init__(self, model.Profesor, extra_parameters)

    def add(self, data, tipo=None):
        # Forzar a que la clave se guarde cifrada
        data.update(password=bcrypt.hash(data["password"]))
        data.update(email=data["email"].lower())
        return DBCollection.add(self, data, model.Profesor)


class Problemas(DBCollection):
    """Listado de problemas"""
    def __init__(self, extra_parameters=None):
        DBCollection.__init__(self, model.Problema, extra_parameters)

    def add(self, data, tipo=None):
        "Añade un problema nuevo a la lista de problemas"

        # Comprobar que se encuentran los campos requeridos
        if not "cuestiones" in data:
            raise TypeError("Faltan las cuestiones en el problema")
        if not data["cuestiones"]:
            raise TypeError("El problema no puede tener una lista vacía de cuestiones")
        if not "creador" in data:
            raise TypeError("El problema debe tener un creador")
        if not data.get("tags"):
            raise TypeError("El problema debe tener una lista de tags")

        # Crear el problema
        email_creador = data["creador"].get("email").lower()
        creador = model.Profesor.get(email=email_creador)
        if not creador:
            raise TypeError("No se reconoce '%s' como creador" % email_creador)
        problema = DBCollection.add(self,
            dict(
                resumen=data.get("resumen"),
                enunciado=data.get("enunciado"),
                creador=creador),
            model.Problema
        )

        # Crear la lista de cuestiones del problema
        for i, q_data in enumerate(data["cuestiones"]):
            q_data["posicion"] = i
            q_data["problema"] = problema
            model.Cuestion(**q_data)

        # Buscar sus tags o crearlos nuevos
        problema.update_tags(data)
        return problema

    def query(self):
        """La lista de problemas puede ir filtrada por tags"""
        # No me gusta cómo está hecho. Traigo de la bbdd todos los problemas
        # y despues me quedo con los que tienen los tags solicitados
        # Seguro que habría forma de hacer la consulta a la base de datos
        # para que traiga sólo los necesarios, pero con Pony no he sido
        # capaz. Siempre se podría crear una sentencia SQL para ello,
        # a base de varios AND con los tags en cuestión.
        #
        # El problema viene de que quiero que sea genérico para cualquier número
        # de tags que se especifique. Si, por ejemplo, supiera que siempre son
        # solo dos tags, podría hacer la siguiente consulta Pony En este caso busco
        # preguntas que tengan los tags "sd" Y "ftp":
        #
        # select(p for p in Problema if JOIN("sd" in p.tags.name and "ftp" in p.tags.name))
        #
        # Eso lo admite Pony, y genera el siguiente SQL:
        #
        # SELECT "p"."id", "p"."resumen", "p"."publicado", "p"."problema_origen", "p"."creador"
        # FROM "Problema" "p"
        # WHERE 'sd' IN (
        #     SELECT "tag"."name"
        #     FROM "Problema_Tag" "t-1", "Tag" "tag"
        #     WHERE "p"."id" = "t-1"."problema"
        #       AND "t-1"."tag" = "tag"."id"
        #     )
        #   AND 'ftp' IN (
        #     SELECT "tag"."name"
        #     FROM "Problema_Tag" "t-1", "Tag" "tag"
        #     WHERE "p"."id" = "t-1"."problema"
        #       AND "t-1"."tag" = "tag"."id"
        #     )
        #
        # Basándome en este código SQL podría crear uno similar con tantos ANDs
        # como tags tenga que buscar, pero me parece aún más sucio
        tags = None
        todos = DBCollection.query(self)
        if self.extra_parameters:
            tags = self.extra_parameters.get("tags")
        if not tags:
            return todos
        tags = set(tags.split(","))

        return [p for p in todos if tags.issubset(p.tags.name)]

    def get_visible_by_user(self, id_):
        """Obtiene la lista de problemas visibles por el usuario cuyo id se
        suministra. Es la unión de los que él ha creado más los que son compartidos
        vía algún círculo"""

        quien = model.Profesor.get(id=id_)
        if quien.role == "admin":
            todos = self.query()
        else:
            creados = model.Problema.select(lambda p: p.creador == quien)
            compartidos = model.Problema.select(lambda p: quien in p.compartido_con.miembros)
            todos = set.union(set(creados), set(compartidos))
        tags = None
        orden = "id"
        reverse = False
        if self.extra_parameters:
            tags = self.extra_parameters.get("tags", None)
            orden = self.extra_parameters.get("orden", orden)
            reverse = self.extra_parameters.get("reverse", reverse)
            if reverse:
                reverse = int(reverse)
        if tags:
            tags = set(tags.split(","))
            todos = [p for p in todos if tags.issubset(p.tags.name)]
        if orden=="id":
            todos = sorted(todos, key=lambda x: x.id, reverse=bool(reverse))
        elif orden in dir(model.Problema):
            todos = sorted(todos, key=lambda x: "%s%05d" % ( getattr(x, orden), x.id),
                           reverse=bool(reverse))
        if orden == "originalidad":
            pass
        return todos


class Tags(DBCollection):
    """Listado de tags"""
    def __init__(self):
        DBCollection.__init__(self, model.Tag)


class Examenes(DBCollection):
    """Listado de examenes"""
    def __init__(self):
        DBCollection.__init__(self, model.Examen)

    @classmethod
    def get_asignatura(cls, asig_dict):
        """Obtiene de la base de datos la Asignatura especificada en el diccionario
        que recibe como parámetro, en el que se espera un campo "@id"."""

        if type(asig_dict) != dict:
            raise TypeError("El campo 'asignatura' del no es un objeto válido")
        id_asignatura = asig_dict.get("@id")
        if not id_asignatura:
            raise TypeError("El campo 'asignatura' del no tiene un id válido")
        id_asignatura = int(id_asignatura.split("/")[-1])
        asignatura = model.Asignatura.get(id=id_asignatura)
        if not asignatura:
            raise TypeError("La asignatura {} es desconocida".format(id_asignatura))
        return asignatura

    def add(self, data, tipo=None):
        "Añade un examen nuevo a la lista de exámenes"

        # Comprobar que se encuentran los campos requeridos
        if not "estado" in data:
            data.update(estado="abierto")
        if not "tipo" in data:
            data.update(tipo="A")
        if not "asignatura" in data:
            raise TypeError("El campo 'asignatura' de un examen no puede estar vacío")
        if not "titulacion" in data:
            raise TypeError("El campo 'titulacion' de un examen no puede estar vacío")
        asignatura = model.Asignatura.get_or_create(
                                        asignatura=data["asignatura"],
                                        titulacion=data["titulacion"])
        if not "fecha" in data:
            raise TypeError("El campo 'fecha' de un examen no puede estar vacío")
        if not "convocatoria" in data:
            raise TypeError("El campo 'convocatoria' de un examen no puede estar vacío")
        if not "creador" in data:
            raise TypeError("El examen debe tener un creador")
        if "intro" not in data:
            raise TypeError("El campo 'intro' debe existir")

        # Crear el problema
        email_creador = data["creador"].get("email").lower()
        creador = model.Profesor.get(email=email_creador)
        if not creador:
            raise TypeError("No se reconoce '%s' como creador" % email_creador)
        examen = dict(
            estado=data.get("estado"),
            tipo=data.get("tipo"),
            asignatura=asignatura,
            fecha=util.my_date_decode(data.get("fecha")),
            convocatoria=data.get("convocatoria"),
            intro=data.get("intro"),
            creador=creador
        )
        return DBCollection.add(self, examen, model.Examen)


class Circulos(DBCollection):
    """Listado de círculos"""
    def __init__(self):
        DBCollection.__init__(self, model.Circulo)

    def add(self, data):
        email_creador = data["creador"].get("email").lower()
        creador = model.Profesor.get(email=email_creador)
        if not creador:
            raise TypeError("No se reconoce '%s' como creador" % email_creador)
        # Ignorar todos los campos salvo el nombre
        campos = list(data.keys())
        for campo in campos:
            if campo != "nombre":
                del data[campo]
        data.update(creador=creador)
        return DBCollection.add(self, data, model.Circulo)


class SubCollection(object):
    """Clase que implementa funcionalidad de objetos que tienen otras listas dentro,
    como la lista de miembros de un círculo, los problemas de un examen, etc."""

    # Todo esto es muy abstracto y difícil de entender y depurar,
    # pero evita repetición de código. Es también bastante frágil porque
    # depende mucho del modelo
    def __init__(self, contenedor, sublista, param=None, full=False):
        # La idea es que esta superclase pueda servir tanto para
        # listas de problemas dentro de un examen, como de
        # problemas dentro de un círculo, o miembros de un círculo
        #
        # Para ello recibe en el constructor cuál es el "contenedor"
        # en cuestión (Circulo o Examen), cuál es el atributo de la
        # clase que contiene la sublista ("miembros", "problemas_visibles")
        # para el caso del Circulo, o "problemas" para el caso del Examen)
        #
        # Del nombre de la sublista "deduce" la clase a que pertenecen
        # los elementos que se pueden insertar en ella
        self.contenedor = contenedor
        self.sublista = sublista
        if sublista == "miembros":
            self.subtype = model.Profesor
        elif sublista == "problemas":
            self.subtype = model.Problema
        elif sublista == "problemas_visibles":
            self.subtype = model.Problema
        self.param = param
        self.full = full

    def query(self):
        # Obtiene por ejemplo Examen.problemas, o Circulo.miembros
        return getattr(self.contenedor, self.sublista)

    def get_collection_ids(self, back=None):
        """Obtiene la lista de ids de los elementos de la subcolección"""
        if self.param == 0:
            return
        # Accede a Circulo.miembros o Examen.problemas por ejemplo
        subcollection = getattr(self.contenedor, self.sublista)
        if back:
            # Permite acceder a Examen.problemas.problema_id
            # para obtener la lista de Problemas
            subcollection = getattr(subcollection, back)
        # Obtener los ids de los elementos en la subcolección
        return subcollection.id

    def is_ok_to_add(self, elem, request):
        """Comprueba si el elemento se puede añadir a la subcolección.
        La condición depende del tipo de subcolección, por lo que deberá
        reescribirse en clases derivadas"""
        # Por defecto cualquier cosa puede añadirse (válido para Profesores en círculos)
        return True

    def check_id_to_add(self, request, back=None):
        """Verifica si el objeto ya estaba en la subcolección, y si
        no estaba si es visible. Retorna el objeto a añadir"""
        # Verifica si ya estaba
        ids_previos = self.get_collection_ids(back)
        if self.param in ids_previos:
            raise ValueError(
                "El elemento de id={} ya estaba en la lista de {}".format(
                    self.param, self.sublista
                ))
        # Si no, obtiene de la BD el elemento a añadir
        elem = self.subtype[self.param]
        self.is_ok_to_add(elem, request)
        return elem

    def check_id_to_remove(self, request, back=None):
        """Verifica si el objeto estaba en la subcolección, retornando
        el objeto en cuestión si estaba, o genera una exepción si no"""
        ids_previos = self.get_collection_ids(back)
        if self.param in ids_previos:
            elem = self.subtype[self.param]
            return elem
        else:
            raise ValueError(
                "El elemento de id={} no estaba en la lista de {}".format(
                    self.param, self.sublista
                )
            )

    def add_element(self, request):
        """Añade un nuevo elemento a la subcolección. El elemento
        será el de id dado por self.param"""
        # Obtener el elemento a añadir (si podemos verlo y no estaba ya)
        elem = self.check_id_to_add(request)
        # Añadirlo, en realidad invoca algo como Circulo.miembros.add()
        getattr(self.contenedor, self.sublista).add(elem)
        self.contenedor.fecha_modificacion = datetime.now()

    def remove_element(self, request):
        """Elimina un elemento de la subcolección. El elemento
        a eliminar será el de id dado por self.param"""
        # Obtener el elemento a eliminar
        elem = self.check_id_to_remove(request)
        getattr(self.contenedor, self.sublista).remove(elem)
        self.contenedor.fecha_modificacion = datetime.now()


class CirculoMiembros(SubCollection):
    """Particularización de SubCollection para miembros de un círculo"""
    def __init__(self, circulo, param=None, full=False):
        SubCollection.__init__(self, circulo, "miembros", param, full)


class CirculoProblemas(SubCollection):
    """Particularización de SubCollection para problemas visibles de un círculo"""
    def __init__(self, circulo, param=None, full=False):
        SubCollection.__init__(self, circulo, "problemas_visibles", param, full)

    def is_ok_to_add(self, elem, request):
        """Un problema sólo puede añadirse a un círculo si somos propietarios del problema"""
        if elem.is_owned(request):
            return True
        raise ValueError(
            "No puedes compartir el problema {} pues no eres propietario".format(self.param))


class ExamenProblemas(SubCollection):
    """Particularización de SubCollection para problemas pertenecientes a un examen"""
    def __init__(self, examen, param=None, full=False):
        SubCollection.__init__(self, examen, "problemas", param, full)

    def is_ok_to_add(self, elem, request):
        """Un problema sólo puede añadirse a un examen si es visible"""
        if elem.is_visible(request):
            return True
        raise ValueError(
            "No puedes añadir el problema {} pues no puedes verlo".format(self.param))

    def add_element(self, request):
        """Añade un nuevo problema al examen. El elemento
        será el de id dado por self.param"""
        # Aquí en lugar de llamar a Examen.add, llamaremos
        # a examen.append_problema, para que lo incluya en la posición
        # adecuada (que será al final)
        elem = self.check_id_to_add(request, back="problema_id")
        self.contenedor.append_problem(elem)

    def remove_element(self, request):
        """Elimina un problema de la subcolección. El elemento
        a eliminar será el de id dado por self.param"""
        # Obtener el elemento a eliminar
        elem = self.check_id_to_remove(request, back="problema_id")
        self.contenedor.remove_problema(elem)
