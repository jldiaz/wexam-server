"""Clases mixin para añadir funcionalidad a los modelos sin tener que tocar los modelos"""

from datetime import datetime, timedelta
from passlib.hash import bcrypt
from pony.orm import commit
from webob.exc import HTTPGatewayTimeout
import redis
import rq

# Se implementan métodos específicos para la "lógica de negocio" de cada modelo.
# Por ejemplo, un profesor, al actualizar la contraseña, debe ser cifrada. Un problema,
# al ser actualizado, debe actualizar a su vez la lista de tags y cuestiones
#
# Estos detalles específicos se implementan en el mixin de cada modelo

class UpdatableMixin(object):
    """Clase genérica para realizar un update en la base de datos, que
    actualice también la fecha_modificacion. Las restantes heredan de ésta"""
    def update(self, data):
        """Actualiza el elemento en la base de datos y la fecha de modificación"""
        data.update(fecha_modificacion=datetime.now())
        self.set(**data)   #pylint:disable=no-member


class ProblemaMixin(UpdatableMixin):
    """Métodos adicionales para la clase Problema"""
    def is_deletable(self, request):
        """Retorna un booleano indicando si el problema se puede borrar. Sólo se puede borrar
        si los examenes en que aparece están abiertos"""

        if not self.is_owned(request):
            return False
        return not self.is_closed()

    def is_closed(self):
        """Retorna un booleano indicando si el problema está en un examen cerrado"""
        for examen in self.examenes.examen_id:
            if examen.estado != "abierto":
                return True
        return False

    def is_visible(self, request):
        """Devuelve True si el usuario actual puede ver este problema
        porque sea su creador o esté en un círculo desde el cual
        el problema sea visible"""
        yo = request.identity
        return permissions.verificar_compartido_problema(
                yo, self, permissions.PoderVer)

    def is_owned(self, request):
        """Devuelve True si el usuario actual es el creador de este problema"""
        yo = request.identity
        return permissions.verificar_propietario(
                yo, self, permissions.SerPropietario)

    def update(self, data):
        """Actualiza datos de un problema"""
        if self.is_closed():
            raise ValueError("El problema no puede modificarse por aparecer en exámenes cerrados")

        problema = self
        # print("ProblemaMixin.update", data)
        # Quedarse sólo con los campos que permitimos actualizar vía PUT
        updatable_fields = ["resumen", "enunciado"]
        data_ok = {}
        for k in updatable_fields:
            if k in data:
                data_ok[k] = data[k]

        # Actualizarlo cuestiones y tags
        cambio_cuestiones = self.update_cuestiones(data)
        cambio_tags = self.update_tags(data)
        # Actualizar el resto, y timestamp
        if data_ok or cambio_cuestiones or cambio_tags:
           # data_ok.update(fecha_modificacion=datetime.now())
           # self.set(**data_ok)
           super().update(data_ok)

    def update_cuestiones(self, data):
        """Actualiza las cuestiones de un problema, de forma inteligente"""
        # Procesar las cuestiones. Es un tema un poco complejo. En el problema recibido en JSON
        # tendremos un campo "cuestiones" que ha de ser una lista de diccionarios. Cada diccionario
        # podría ser una cuestión que ya existía en el problema, o una cuestión nueva. La forma
        # de diferenciarlo es que las que ya existían traen el atributo @id y las nuevas no.
        #
        # No obstante, aunque haya cuestiones que no se modifiquen, deben aparecer en el listado
        # de cuestiones, con su @id, ya que todas aquellas que estuvieran antes en el problema
        # pero no aparezcan en el JSON, serán eliminadas (se entiende que el usuario borró
        # esas cuestiones del problema)
        problema = self
        dirty = False
        if "cuestiones" in data:
            qids_originales = [ q.id for q in problema.cuestiones ]  # ids de las que tenía el problema
            qids_recibidos = []                           # ids de las que se modifican con PUT
            qids_creados = []                             # ids de las nuevas que vienen en el PUT
            # Procesamos las que vienen en el JSON
            for i, q_data in enumerate(data["cuestiones"]):
                # Si no es un diccionario, error
                if type(q_data)!=dict:
                    raise TypeError("Las cuestiones no están en el formato apropiado")
                # Si vienen con un ID, intentar actualizar esa cuestión
                if "id" in q_data:
                    qid = int(q_data["id"])
                    # Verificar que la que intentan modificar formaba parte del problema
                    if qid not in qids_originales:
                        raise TypeError("La pregunta con id=%d no era de este problema" % qid)
                    qids_recibidos.append(qid)
                    # Actualizar la pregunta con lo que viene en el JSON
                    del q_data["id"]
                    q_data["posicion"] = i
                    model.Cuestion[qid].set(**q_data)
                    dirty = True
                else:
                    # Si no tiene @id, crear una cuestión nueva, asociada a este problema
                    q_data["posicion"] = i
                    q_data["problema"] = problema
                    q = model.Cuestion(**q_data)
                    # Guardarla en la base de datos para obtener su nuevo id
                    commit()
                    qids_creados.append(q.id)
                    dirty = True
            # Ahora eliminar las cuestiones cuyo id no está entre las recibidas o creadas
            for q in problema.cuestiones:
                if q.id not in qids_recibidos + qids_creados:
                    q.delete()
                    dirty = True
        return dirty

    def update_tags(self, data):
        """Actualiza los tags de un problema y la tabla de Tags de la base de datos,
        si es necesario"""
        # Consulta a la base de datos para extraer cuáles de los tags usados
        # en este problema ya estaban en la bbdd
        if not "tags" in data:
            return False
        problema = self
        # Borrar lo que habia y cambiarlo por lo que llega
        problema.tags.clear()
        tags_existentes = model.Tag.select(lambda t: t.name in data["tags"])
        # Añadir esos objetos
        for tag in tags_existentes:
            problema.tags.add(tag)
        # Calcular cuáles son los nombres de los tags nuevos,
        # para crearlos en la base de datos y añadirlos también al problema
        tags_nuevos = set(data["tags"]) - set(t.name for t in tags_existentes)
        for tag in tags_nuevos:
            problema.tags.add(model.Tag(name=tag))
        commit()
        # Eliminar de la bbdd los tags que ya no son usados
        model.Tag.select(lambda t: not t.problemas).delete(bulk=True)
        return True

    def delete_object(self):
        """Elimina el problema de la base de datos y actualiza la tabla de Tags si es necesario
        para eliminar los tags huérfanos"""
        if self.is_closed():
            raise ValueError("El problema no puede borrarse por aparecer en exámenes cerrados")
        self.delete()
        model.Tag.select(lambda t: not t.problemas).delete(bulk=True)
        return True

    def clone(self, request):
        """Crea un clon del problema. El clon tiene todos los datos idénticos
        a los del problema original, salvo:

        * resumen (lleva un sufijo añadido al final)
        * creador (es el usuario identificado en el token)
        * compartido_con (vacío)
        * examenes en que aparece (vacío)
        * problema_origen (el problema original que está siendo clonado)
        * fecha_creacion = fecha_modificacion = now
        """
        creador = model.Profesor.get(id=request.identity.id)

        sufijo = ".{}".format(len(self.problemas_derivados)+1)

        problema = model.Problema(
            resumen = self.resumen + sufijo,
            enunciado = self.enunciado,
            metainfos = self.metainfos,
            problema_origen = self,
            figuras = self.figuras,
            tags = self.tags,
            creador = creador,
            fecha_creacion = datetime.now(),
            fecha_modificacion = datetime.now(),
        )
        # Clonar cuestiones (creando nuevas)
        for q in self.cuestiones:
            model.Cuestion(
                enunciado = q.enunciado,
                respuesta = q.respuesta,
                explicacion = q.explicacion,
                puntos = q.puntos,
                problema = problema,
                posicion = q.posicion
            )
        commit()
        return problema


class ExamenMixin(UpdatableMixin):
    """Métodos adicionales para la clase Examen"""
    def clear_all_problemas(self):
        """Elimina todos los problemas del examen"""
        self.problemas.clear()
        self.fecha_modificacion = datetime.now()

    def remove_problema(self, problema):
        """Elimina el problema dado de este examen"""
        self.problemas.remove(model.Problema_examen[problema, self])
        self.fecha_modificacion = datetime.now()

    def delete_problemas(self, request):
        """Elimina los problemas dados en request.json["problemas"] del examen actual,
        y ante un error en la lista de problemas a borrar, aborta la operación
        sin borrar ninguno"""
        _, _, para_quitar = self.verificar_y_separar_problemas(request)
        if not para_quitar:
            raise ValueError("Los problemas especificados no formaban parte de este examen")
        else:
            # Quitar las relaciones
            self.problemas.remove([model.Problema_examen[p, self] for p in para_quitar])
            self.fecha_modificacion = datetime.now()

    def append_problem(self, problema):
        """Añade el problema dado al final de los existentes"""
        if self.problemas.posicion:
            ultimo_indice = max(self.problemas.posicion) + 1
        else:
            ultimo_indice = 1
        self.problemas.add(
            model.Problema_examen(posicion=ultimo_indice,
                        examen_id=self, problema_id=problema))
        self.fecha_modificacion = datetime.now()

    def add_problemas(self, request):
        """Añade al examen actual la lista de problemas que recibe en request["problemas"]
        Pero verifica antes de hacerlo si es posible. Si alguno falla, la operación
        completa se cancela y no se añade ninguno"""

        a_añadir, no_se_puede, _ = self.verificar_y_separar_problemas(request)

        # Una vez verificados todos, si alguno no se puede, abortar operación
        if no_se_puede:
            raise ValueError("La lista de problemas a añadir contiene problemas no válidos")
        # Si no quedó ninguno a añadir, también abortamos con error
        elif not a_añadir:
            raise ValueError("Los problemas a añadir ya formaban parte del examen")
        else:
            # Si todo pasa, añadimos los problemas nuevos, al final de los que ya había
            if self.problemas.posicion:
                ultimo_indice = max(self.problemas.posicion) + 1
            else:
                ultimo_indice = 1
            for n, problema in enumerate(a_añadir):
                self.problemas.add(
                    model.Problema_examen(posicion=ultimo_indice + n, 
                                          examen_id=self, problema_id=problema))
            self.fecha_modificacion = datetime.now()

    def update_problemas(self, request):
        """Sustituye la lista de problemas que había en el examen por otra
        que recibe en request.json["problemas"]"""

        a_añadir, no_se_puede, ya_estaban = self.verificar_y_separar_problemas(request)
        # Una vez verificados todos, si alguno no se puede, abortar operación
        if no_se_puede:
            raise ValueError("La lista de problemas a añadir contiene problemas no válidos")
        # Si todos se pueden (son nuevos o ya estaban), entonces quitamos todos y después
        # añadimos
        self.clear_all_problemas()
        commit()
        self.add_problemas(request)
        self.fecha_modificacion = datetime.now()

    def update_asignatura(self, data):
        """Actualiza la asignatura asociada al problema y la tabla Asignaturas de
        la base de datos, si es necesario"""
        # Consulta a la base de datos para extraer la asignatura
        if not "asignatura" in data:
            return False
        if not "titulacion" in data:
            raise ValueError("No puede aparecer el campo asignatura sin titulación.")
        asignatura = model.Asignatura.get_or_create(
                                        asignatura=data["asignatura"],
                                        titulacion=data["titulacion"])
        if asignatura == self.asignatura:
            return False
        self.asignatura = asignatura
        return True

    def update_estado(self, nuevo_estado):
        """Actualizar "inteligentemente" el estado del examen"""

        if nuevo_estado not in ["abierto", "cerrado", "publicado"]:
            raise ValueError("El estado '{}' no es válido".format(nuevo_estado))

        transicion = [self.estado, nuevo_estado]
        data_ok = {}

        if transicion[0] == "publicado":
            # Del estado publicado no podemos pasar a ningún otro
            raise ValueError("El examen no puede modificarse porque está publicado")

        if transicion[0] == transicion[1]:
            # De un estado al mismo estado, no actualizamos nada
            return

        # if transicion == ["cerrado", "abierto"]:
        #     # De cerrado a abierto miramos si estamos en la ventana de tiempo
        #     if datetime.now() - self.fecha_modificacion > timedelta(hours=24):
        #         raise ValueError("El examen no puede reabrirse pasadas 24h.")

        if transicion[1] == "publicado":
            # Desde cualquier estado podemos pasar a publicado, y almacenamos la fecha
            # de la publicación
            data_ok.update(publicado = datetime.now())

        # El resto de transiciones están permitidas
        data_ok.update(estado = transicion[1])
        super().update(data_ok)

    def verificar_y_separar_problemas(self, request):
        """Esta función recibe una petición que tendrá un campo "problemas" con una serie
        de problemas que se pretenden incorporar o eliminar del examen dado.

        Retorará tres listas:
          * La primera contendrá los problemas que se pueden añadir al examen (porque han
          pasado el test de existir, no formar ya parte del examen, y ser visibles para el usuario)
          * La  segunda contendrá los problemas que no se pueden añadir al examen (porque no
          existen o no se tiene permiso para verlos)
          * La tercera contendrá los problemas que ya estaban en el examen
        """
        a_añadir = []
        no_se_puede = []
        ya_estaban = []
        yo = request.identity
        lista = request.json.get("problemas")
        if not lista:
            raise ValueError("No se especificó la lista de problemas")
        # El siguiente bucle va mirando los ids de los problemas que se pretenden añadir al examen
        # para verificar si existen, si ya estaban en el examen, o si tenemos permiso para verlos
        # y va construyendo las listas a_añadir (con los que pasan los test) y no_se_puede 
        # (con los que no)
        for problema in lista:
            # Verificar formato de lo que se recibe, y extracción del id
            if type(problema) != dict:
                raise ValueError("La lista de problemas no contiene objetos válidos")
            id = problema.get("id")
            if not id:
                raise ValueError("Los objetos problema no tienen campo id")
            # Extraer el problema de la bd (si existe)
            try:
                prob = model.Problema[id]
            except ObjectNotFound:
                no_se_puede.append(id)
                prob = None
            # Si ya estaba en el examen, saltárselo
            if prob in self.problemas.problema_id:
                ya_estaban.append(prob)
                continue
            # Si tenemos permiso para verlo, añadirlo a la lista
            if permissions.verificar_compartido_problema(yo, prob, permissions.PoderVer):
                a_añadir.append(prob)
            else:
                no_se_puede.append(id)
        if len(a_añadir) != len(set(a_añadir)) or len(ya_estaban) != len(set(ya_estaban)):
            raise ValueError("La lista de problemas contiene elementos duplicados")
            # Si hay duplicados en no_se_puede no importa, ya que
            # no se hará nada con ellos de todas formas
        return a_añadir, no_se_puede, ya_estaban

    def update(self,data):
        """Actualiza datos de un examen (no sus problemas o círculos)"""

        examen = self

        if "estado" in data:
            # Actualizar primero el estado
            self.update_estado(data["estado"])

        if examen.estado != "abierto":
            if examen.estado != data["estado"]:
                raise ValueError("El examen no puede modificarse por no estar abierto")
            else:
                return self

        # Quedarse sólo con los campos que permitimos actualizar vía PUT
        updatable_fields = ["estado", "tipo", "fecha", "convocatoria", "intro"]
        data_ok = {}
        for k in updatable_fields:
            if k in data:
                if k=="fecha":
                    data_ok[k] = util.my_date_decode(data[k])
                elif k=="asignatura":
                    data_ok[k] = coll.Examenes.get_asignatura(data[k])
                else:
                    data_ok[k] = data[k]
        # Actualizar asignatura (creando una si es necesario)
        if self.update_asignatura(data):
            # Purgar tabla de asignaturas no usadas
            asig_huerfanas = model.Asignatura.select(lambda a: not a.examenes)
            asig_huerfanas.delete()

        # Actualizar resto de campos del examen
        super().update(data_ok)

    def delete_object(self):
        """Borra el examen, comprobando antes que esté abierto"""
        if self.estado != "abierto":
            raise ValueError("El examen no puede borrarse por no estar abierto")
        self.delete()
        return None


class ProfesorMixin(UpdatableMixin):
    """Funciones adicionales para el modelo Profesor"""
    def update(self, data):
        """Actualiza los datos del profesor, asegurándose de que la clave va cifrada
        a la base de datos"""
        if "password" in data:
            data.update(password=bcrypt.hash(data["password"]))
        super().update(data)

    def lanzar_tarea(self, request, nombre, *args, **kwargs):
        if request.app.redis is None:
            return None
        try:
            rq_job = request.app.task_queue.enqueue('tasks.{}'.format(nombre), *args, **kwargs)
            #print(kwargs)
        except redis.exceptions.TimeoutError:
            raise HTTPGatewayTimeout("El backend redis no responde")
        if "formato" in kwargs:
            tipo = kwargs["formato"]
        else:
            tipo = "bytes"
        task = model.Tarea(id=rq_job.get_id(), nombre=nombre, creador=self, tipo=tipo)
        return task


class CirculoMixin(UpdatableMixin):
    """Funciones adicionales para el manejo de circulos"""

    def update(self, data):
        """Actualiza el círculo, usando sólo el campo data["nombre"]"""
        if "nombre" not in data:
            return
        super().update({"nombre": data["nombre"]})

    def add_profesores(circulo, data):
        """Añade al círculo la lista de profesores que recibe en data["miembros"]
        asegurándose de que todos existen. Si alguno no existiera, no se añadiría ninguno"""
        a_añadir = []
        for profesor in data.get("miembros"):
            i = int(profesor["id"])
            if model.Profesor[i] not in circulo.miembros:
                a_añadir.append(model.Profesor[i])
        if not a_añadir:
            raise ValueError("No hay profesores que añadir")
        # Ahora añadirlos
        circulo.miembros.add(a_añadir)
        circulo.fecha_modificacion = datetime.now()

    def remove_profesores(circulo, data):
        """Elimina del círculo los profesores que reciba en la lista data["miembros"]
        verificando primero que existan (si alguno no existiera, no se eliminaría ninguno)"""
        a_quitar = []
        for profesor in data.get("miembros"):
            i = int(profesor["id"])
            if model.Profesor[i] in circulo.miembros:
                a_quitar.append(model.Profesor[i])
        if not a_quitar:
            raise ValueError("No hay profesores que quitar")
        # Ahora quitarlos
        circulo.miembros.remove(a_quitar)
        circulo.fecha_modificacion = datetime.now()

    def verificar_y_separar_problemas(self, request):
        """Esta función recibe una petición que tendrá un campo "problemas" con una serie
        de problemas que se pretenden incorporar o eliminar del círculo dado.

        Retorará tres listas:
          * La primera contendrá los problemas que se pueden añadir al círculo (porque han
          pasado el test de existir, no formar ya parte del círculo, y ser creación del usuario)
          * La  segunda contendrá los problemas que no se pueden añadir al círculo (porque no
          existen o no se es el creador)
          * La tercera contendrá los problemas que ya estaban en el círculo
        """
        a_añadir = []
        no_se_puede = []
        ya_estaban = []
        yo = request.identity
        lista = request.json.get("problemas")
        if not lista:
            raise ValueError("No se especificó la lista de problemas")
        for problema in lista:
            # Verificar formato de lo que se recibe, y extracción del id
            if type(problema) != dict:
                raise ValueError("La lista de problemas no contiene objetos válidos")
            id = problema.get("id")
            if not id:
                raise ValueError("Los objetos problema no tienen campo id")
            # Extraer el problema de la bd (si existe)
            try:
                prob = model.Problema[id]
            except ObjectNotFound:
                no_se_puede.append(id)
                prob = None
            if prob is None:
                continue
            # Si ya estaba en el círculo, saltárselo
            if prob in self.problemas_visibles:
                ya_estaban.append(prob)
                continue
            # Si el usuario lo creó, añadir a la lista
            if permissions.verificar_propietario(yo, prob, permissions.SerPropietario):
                a_añadir.append(prob)
            else:
                no_se_puede.append(id)
        if len(a_añadir) != len(set(a_añadir)) or len(ya_estaban) != len(set(ya_estaban)):
            raise ValueError("La lista de problemas contiene elementos duplicados")
            # Si hay duplicados en no_se_puede no importa, ya que
            # no se hará nada con ellos de todas formas
        return a_añadir, no_se_puede, ya_estaban

    def add_problemas(circulo, request):
        """Añade al círculo la lista de problemas que recibe en data["problemas"]
        asegurándose de que todos existen y que han sido creados por el usuario.
        Si alguno no existiera, no se añadiría ninguno"""

        a_añadir, no_se_puede, _ = circulo.verificar_y_separar_problemas(request)
        if not a_añadir:
            raise ValueError("No hay problemas que añadir")
        # Ahora añadirlos
        circulo.problemas_visibles.add(a_añadir)
        circulo.fecha_modificacion = datetime.now()

    def remove_problemas(circulo, request):
        """Elimina del círculo los problemas que reciba en la lista data["problemas"]
        verificando primero que existan (si alguno no existiera, no se eliminaría ninguno)"""
        _, _, a_quitar = circulo.verificar_y_separar_problemas(request)
        if not a_quitar:
            raise ValueError("No hay problemas que quitar del círculo")
        # Ahora quitarlos
        circulo.problemas_visibles.remove(a_quitar)
        circulo.fecha_modificacion = datetime.now()


class AsignaturaMixin(UpdatableMixin):
    """Funciones extra para manejo de asignaturas en la base de datos"""
    def get_or_create(asignatura, titulacion):
        a = model.Asignatura.get(nombre=asignatura, titulacion=titulacion)
        if not a:
            a = model.Asignatura(nombre=asignatura, titulacion=titulacion)
            commit()
        return a


class TareaMixin(object):
    def get_rq_job(self, request):
        if request.app.redis is None:
            return None
        try:
            rq_job = rq.job.Job.fetch(self.id, connection=request.app.redis)
        except redis.exceptions.TimeoutError:
            raise HTTPGatewayTimeout("El backend redis no responde")
        except (redis.exceptions.RedisError, rq.exceptions.NoSuchJobError):
            return None
        return rq_job

    def get_progress(self, request):
        if request.app.redis is None:
            return "No disponible"
        job = self.get_rq_job(request)
        return job.meta.get('progreso', "Esperando") if job is not None else "Completada"

    def get_status(self, request):
        if request.app.redis is None:
            return {
                "status": "No disponible",
                "msg": "El servidor no implementa esta funcionalidad"
            }
        job = self.get_rq_job(request)
        if job is None:
            self.creador.tareas.remove(self)
            return {
                "status": "Borrada",
                "msg": "Debes lanzar de nuevo la conversión"
            }
        if job.is_failed:
            self.delete()
            return {
                "status": "Fallida",
                "msg": str(job.exc_info)
            }
        if job.is_finished:
            return {
                "status": "Completada",
            }
        return {
            "status": self.get_progress(request),
        }

    def get_result(self, request):
        if request.app.redis is None:
            return None
        job = self.get_rq_job(request)
        if job is None:
            return None
        self.delete()
        return job.result



# Algunos import van al final, para eliminar dependencias circulares
from . import permissions
from . import model
from . import db_collections as coll
from . import util
from pony.orm.core import ObjectNotFound
