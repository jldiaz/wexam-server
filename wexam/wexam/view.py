"""Vistas de cada una de las rutas, que generan el JSON que se responde al cliente
o bien lanzan una excepción que será finalmente traducida a un código HTTP en caso
de errores en los parámetros, objetos no encontrados, o permisos insuficientes.

Este módulo implementa también los permisos y la autenticación con JWT.
"""

from collections import Counter
import json
import time
import collections
import traceback
import sys

import yaml
from pony.orm.core import ObjectNotFound
import more.pony
import morepath
import webob
from morepath.core import date_encode
from morepath.core import datetime_encode
from morepath import Response
from webob.exc import (HTTPUnauthorized, HTTPNotFound,
        HTTPMethodNotAllowed, HTTPForbidden)
from passlib.hash import bcrypt
from more.jwtauth import JWTIdentityPolicy

from .tests.crear_db_ejemplo import crear_db_ejemplo
from .app import App
from . import model
from . import appmodel
from . import db_collections as coll
from .permissions import *

# ==================== VISTAS "ADMINISTRATIVAS" ==================================
@App.json(model=appmodel.Root, permission=EstarRegistrado)
def view_root(self, request):  # pylint: disable=unused-argument
    """Por implementar. De momento retornamos una especie de "directorio" de la API"""
    return {
        "profesores": request.link(coll.Profesores()),
        "examenes": request.link(coll.Examenes()),
        "problemas": request.link(coll.Problemas()),
        "tags": request.link(coll.Tags()),
        "circulos": request.link(coll.Circulos())
    }

# Vista de Login
@App.json(model=appmodel.Login)
def view_login_get(self, request): # pylint: disable=unused-argument
    """La ruta /login no debe ser accedida con GET, sino con POST"""
    raise HTTPUnauthorized('Debes suministrar email y clave con POST')

@App.json(model=appmodel.Login, request_method="POST")
def view_login_post(self, request): # pylint: disable=unused-argument
    """Valida usuario y contraseña y genera JWT, que se envía en una cabecera
    Authorization"""
    email = request.json.get("email", "").lower()
    password = request.json.get("password")
    quien = model.Profesor.get(email=email)
    if (not quien or not password or not email or
            not bcrypt.verify(password, quien.password)):
        raise HTTPUnauthorized('Nombre de usuario o contraseña no válidos')

    identidad = morepath.Identity(email, nombre=quien.nombre,
                                  id=quien.id, role=quien.role)

    @request.after
    def enviar_jwt_a_cliente(response):  # pylint: disable=unused-variable
        """Esta función se ejecutará una vez la petición ha sido procesada
        sin errores. Añadirá la cabecera Authority con el JWT"""
        request.app.remember_identity(response, request, identidad)

    fake_response = Response()
    request.app.remember_identity(fake_response, request, identidad)
    return fake_response.headers['Authorization']

@App.json(model=appmodel.ResetPassword)
def view_reset_password(self, request):
    """Envía al usuario un email con un enlace para reiniciar la clave"""
    self.envia_enlace_reiniciar_clave(request.link(self, name="ok"),
                                      request.app.settings)
    return {"ok":"mensaje enviado"}

@App.html(model=appmodel.ResetPassword, name="ok")
def view_form_reset_password(self, request): # pylint: disable=unused-argument
    """Verifica el token y admite el reinicio de clave"""

    pagina = open(request.app.settings.static.folder + "/reset-password.html").read()
    return pagina

@App.json(model=appmodel.ResetPassword, name="ok", request_method="POST")
def view_perform_password_change(self, request):
    """Verifica el JWT recibido y que concuerda con los datos que vienen en el
    POST y si todo es correcto cambia la contaseña a la especificada en el cuerpo del POST"""

    if 'token' not in request.GET:
        raise TypeError("Falta el token en la URL")
    if 'password' not in request.json:
        raise TypeError("Falta JSON con 'password'")
    todo_ok = self.validate_token(request.GET['token'])
    if todo_ok:
        self.quien.update({"password": request.json["password"]})
        return {"ok": "contraseña cambiada!"}
    else:
        raise TypeError("El token es inválido")


# ==================== ENTIDADES DEL MODELO =======================================
with App.json(model=model.Profesor) as view:
    @view(name="min", permission=EstarRegistrado)
    def view_profesor(self, request):
        "Obtener datos mínimos de un profesor"
        return {
            'id': self.id,
            'nombre': self.nombre,
        }

    @view(permission=SerPropietario)
    def view_professor(self, request):
        "Obtener datos completos de un profesor"
        data = request.view(self, name="min")
        data.update(role=self.role, email=self.email,
            fecha_creacion=datetime_encode(self.fecha_creacion),
            fecha_modificacion=datetime_encode(self.fecha_modificacion),
            )
        return data

    @view(request_method="PUT", permission=SerPropietario)
    def update_profesor(self, request):
        "Modificar datos de un profesor"
        self.update(request.json)
        return request.view(self)

    @view(request_method="DELETE", permission=SerAdmin)
    def delete_profesor(self, request):
        "Eliminar un profesor"
        profesores = coll.Profesores()
        if profesores.delete_object(self.id) is None:
            return None
        return morepath.Response(status=204)

with App.json(model=model.Problema) as view:
    @view(name="min", permission=PoderVer)
    def view_problem_mini(self, request):
        """Obtener JSON minimo de un problema, sólo su resumen, tags,
        número de cuestiones y puntos"""
        snippet = [self.enunciado]
        if self.enunciado:
            snippet.append("\n")
        snippet.extend(["- {}\n".format(q.enunciado) for q in 
                        self.cuestiones.order_by(model.Cuestion.posicion)])
        snippet = "".join(snippet)
        return {
            "id": self.id,
            "resumen": self.resumen,
            "tags": sorted([t.name for t in self.tags]),
            "puntos": sum(c.puntos for c in self.cuestiones),
            "n_cuestiones": len(self.cuestiones),
            "creador": {"nombre": self.creador.nombre,
                        "id": self.creador.id},
            "originalidad": self.simhash,
            "snippet": snippet,
            "n_examenes": len(self.examenes),
            "publicado": any((e.examen_id.estado == "publicado" for e in self.examenes)),
            "es_borrable": self.is_deletable(request),
            "es_compartible": self.is_owned(request)
        }

    @view(name="tags", permission=PoderVer)
    def view_problem_tags(self, request):
        """Obtener lista de tags del problema"""
        return  {
            "id": self.id,
            "tags": [t.name for t in self.tags]
        }

    @view(name="examenes", permission=PoderVer)
    def view_problem_exam(self, request):
        """Obtener lista de exámenes en los que el problema aparece"""
        return {
            "id": self.id,
            "_links": [request.link(e.examen_id) for e in self.examenes],
            "examenes": [e.examen_id.id for e in self.examenes]
        }

    @view(name="isdeletable", permission=SerPropietario)
    def is_deletable(self, request):
        """Retorna false si el problema no se puede borrar por estar en examenes
        no abiertos"""
        return {
            "is_deletable": self.is_deletable(request)
        }

    @view(permission=PoderVer)
    def view_problema(self, request):
        """Obtener JSON de un problema, pero sin el texto de las cuestiones,
        sólo con enlaces a ellas"""
        data = request.view(self, name="min")
        data.update(
            enunciado=self.enunciado,
            problema_origen=self.problema_origen.id if self.problema_origen else None,
            problemas_derivados=[p.id for p in self.problemas_derivados],
            cuestiones=[request.link(c)
                        for c in self.cuestiones
                        .order_by(model.Cuestion.posicion)],
            figuras=[request.link(f) for f in self.figuras],
            compartido=[request.view(c, name="min") for c in self.compartido_con]
        )
        return data

    @view(name="meta", permission=PoderVer)
    def view_problem_metainfo(self, request):
        "Obtener meta-información de un problema"
        return {
            "id": self.id,
            "metainfo": [m.info for m in self.metainfos]
        }

    @view(name="data", permission=PoderVer)
    def view_problema_data(self, request):
        """Obtener los datos relevantes del problema para la exportación JSON"""
        info = request.view(self)
        info.update(
            cuestiones=[request.view(c) for c in
                        self.cuestiones.order_by(model.Cuestion.posicion)],
            puntos=sum(c.puntos for c in self.cuestiones),
        )
        return info

    @view(name="full", permission=PoderVer)
    def view_problema_full(self, request):
        """Obtener versión 'expandida' del problema, con el contenido de
        cada una de sus cuestiones"""
        # Obtenemos primero la versión general y le añadimos
        # las cuestiones "expandidas"
        info = request.view(self, name="data")
        info.update(
            fecha_creacion=datetime_encode(self.fecha_creacion),
            fecha_modificacion=datetime_encode(self.fecha_modificacion),
            examenes = [request.view(e.examen_id, name="min") for e in self.examenes],
        )
        return info

    @view(name="yaml", permission=PoderVer)
    def view_problema_yaml(self, request):
        """Obtener versión Yaml del problema, como opción de exportación"""
        headers = {"Content-type": "application/x-yaml",
                    "Content-disposition": 'attachment; filename="problema-{}.{}"'.format(
                        self.id, "-".join(self.tags.name))
                  }
        orig_data = request.view(self, name="full")
        data = collections.OrderedDict()
        data['resumen'] = orig_data["resumen"]
        data["enunciado"] = orig_data["enunciado"]
        data["cuestiones"] = [
            collections.OrderedDict(
                (("enunciado", q["enunciado"]),
                ("respuesta", q["respuesta"]),
                ("puntos", q["puntos"])))
                for q in orig_data["cuestiones"]
            ]
        data["tags"] = orig_data["tags"]
        data["puntos"] = orig_data["puntos"]
        data["fecha_creacion"] = orig_data["fecha_creacion"]
        data["fecha_modificacion"] = orig_data["fecha_modificacion"]
        data["creador"] = orig_data["creador"]["nombre"]
        data["problema_origen"] = orig_data["problema_origen"]
        data["problemas_derivados"] = orig_data["problemas_derivados"]
        data["examenes"] = [{"asignatura": e["asignatura"],
                            "fecha": e["fecha"],
                            "estado": e["estado"]} for e in orig_data["examenes"]]

        content = yaml.dump(data, allow_unicode=True, default_flow_style=False)
        return morepath.Response(body=content, status=200, headers=headers)

    @view(request_method="DELETE", permission=SerPropietario)
    def delete_problema(self, request):
        """Eliminar un problema"""
        problemas = coll.Problemas()
        if self.delete_object() is None:
            return None
        return morepath.Response(status=204)

    @view(request_method="PUT", permission=SerPropietario)
    def update_problema(self, request):
        "Modificar datos de un problema"
        # coll.Problemas().update(self.id, request.json)
        self.update(request.json)
        return request.view(self)

    @view(name="clone", request_method="POST", permission=PoderVer)
    def clone_problem(self, request):
        """Crea un clon del problema"""
        problema = self.clone(request)
        @request.after
        def after(response):
            """Cambia status 200 a 201"""
            response.status = 201
        return request.view(problema)

with App.json(model=model.Tarea) as view:
    @view(permission=SerPropietario)
    def get_tarea(self, request):
        estado = self.get_status(request)
        if estado == None:
            return None
        if estado["status"] == "Completada":
            estado["link"] = request.link(self, name="download")
        return estado

with App.view(model=model.Tarea) as view:
    @view(name="download", permission=SerPropietario)
    def download_task_result(self, request):
        content = self.get_result(request)
        if type(content) == tuple:
            content = content[-1]
        if self.tipo == "zip":
            mimetype = "application/zip"
        elif self.tipo == "pdf":
            mimetype = "application/pdf"
        elif self.tipo == "tgz" or self.tipo == "tar.gz":
            mimetype = "application/gzip"
        else:
            mimetype = "application/octect-stream"
        headers = {"Content-type": mimetype,
                    "Content-disposition": 'attachment; filename="examen.{}"'.format(self.tipo)
                  }
        return morepath.Response(body=content, status=200, headers=headers)

with App.json(model=model.Cuestion) as view:
    @view(permission=PoderVer)
    def view_cuestion(self, request):
        "Obtener JSON de una cuestión"
        return {
            "id": self.id,
            "enunciado": self.enunciado,
            "respuesta": self.respuesta,
            "explicacion": self.explicacion,
            "puntos": self.puntos
        }

with App.json(model=model.Tag) as view:
    @view(name="min", permission=EstarRegistrado)
    def view_tag_str(self, request): # pylint: disable=unused-argument
        "Obtener cadena de un Tag"
        return self.name

    @view(permission=EstarRegistrado)
    def view_tag(self, request):
        "Obtener info de tag"
        return {
            "name": self.name,
            "id": self.id,
        }

    @view(name="full", permission=EstarRegistrado)
    def view_tag_full(self, request):
        "Obtener info de tag"
        info = request.view(self)
        info.update(usado=self.problemas.count())
        return info

with App.json(model=model.Examen) as view:
    @view(name="min", permission=SerPropietario)
    def view_examen_min(self, request):
        "Obtener JSON minimo del examen, sólo asignatura, fecha y convocatoria"
        return {
            "id": self.id,
            "estado": self.estado,
            "asignatura": self.asignatura.nombre,
            "titulacion": self.asignatura.titulacion,
            "fecha": date_encode(self.fecha),
            "convocatoria": self.convocatoria,
            "tipo": self.tipo,
            "publicado": date_encode(self.publicado) if self.publicado else None,
            "creador": {"nombre": self.creador.nombre,
                        "id": self.creador.id},
        }

    @view(permission=SerPropietario)
    def view_examen(self, request):
        """Obtener JSON del examen, con todos los detalles generales pero
        sin el texto de sus problemas sino enlaces a ellos"""
        data = request.view(self, name="min")
        data.update(
            intro=self.intro,
            problemas=[request.view(p.problema_id, name="min")
                       for p in self.problemas
                       .order_by(model.Problema_examen.posicion)],
        )
        return data

    @view(name="data", permission=SerPropietario)
    def view_examen_data(self, request):
        """Obtener JSON del examen, con todos los detalles necesarios para la exportación
        o posible generación de una versión imprimible"""

        info = request.view(self)
        info.update(
            fecha_creacion = datetime_encode(self.fecha_creacion),
            fecha_modificacion = datetime_encode(self.fecha_modificacion),
            problemas=[request.view(p.problema_id, name="data") for p in
                       self.problemas.order_by(model.Problema_examen.posicion)]
        )
        return info

    @view(name="full", permission=SerPropietario)
    def view_examen_full(self, request):
        """Obtener JSON del examen, con todos los detalles generales incluyendo
        todas las preguntas, sus respuestas, etc. A partir de esta información
        debería ser posible generar el examen impreso, salvo por las figuras
        externas si las hubiere"""

        # Obtenemos la representación general y le añadimos
        # los problemas "expandidos"
        info = request.view(self)
        info.update(
            fecha_creacion = datetime_encode(self.fecha_creacion),
            fecha_modificacion = datetime_encode(self.fecha_modificacion),
            problemas=[request.view(p.problema_id, name="full") for p in
                       self.problemas.order_by(model.Problema_examen.posicion)]
        )
        return info

    @view(request_method="DELETE", permission=SerPropietario)
    def delete_examen(self, request):
        """Eliminar un examen"""
        self.delete_object()
        return morepath.Response(status=204)

    @view(request_method="PUT", permission=SerPropietario)
    def update_examen(self, request):
        "Modificar datos de un examen"
        self.update(request.json)
        return request.view(self)

    @view(name="problemas", permission=SerPropietario)
    def get_examen_problemas(self, request):
        return {
            "id": self.id,
            "problemas": [request.view(p.problema_id, name="min") for p in
                       self.problemas.order_by(model.Problema_examen.posicion)]
        }

    @view(name="problemas", request_method="POST", permission=SerPropietario)
    def post_examen_problemas(self, request):
        """Intenta añadir problemas a un examen"""
        self.add_problemas(request)
        return request.view(self, name="problemas")

    @view(name="problemas_todos", request_method="DELETE", permission=SerPropietario)
    def delete_examen_problemas(self, request):
        """Elimina todos los problemas de un examen"""
        self.clear_all_problemas()
        return request.view(self, name="problemas")

    @view(name="problemas", request_method="DELETE", permission=SerPropietario)
    def delete_examen_problemas(self, request):
        """Elimina problemas dados de un examen"""
        self.delete_problemas(request)
        return request.view(self, name="problemas")

    @view(name="problemas", request_method="PUT", permission=SerPropietario)
    def update_examen_problemas(self, request):
        """Elimina todos los problemas del examen y añade los que recibe en la petición"""
        self.update_problemas(request)
        return request.view(self, name="problemas")

    @view(name="download")#, permission=SerPropietario)
    def download_examen(self, request):
        examen_json = request.view(self, name="data")
        formato = request.GET.get("formato", "json")
        resuelto = request.GET.get("resuelto", "noresuelto").lower()
        sync = request.GET.get("sync", False)

        if sync == "true" or sync == "1":
            sync = True
        else:
            sync = False

        if resuelto in ["false", "no"]:
            resuelto = "noresuelto"
        elif resuelto in ["true", "si", "sí"]:
            resuelto = "resuelto"
        elif resuelto == "explicado":
            pass
        else:
            resuelto = "noresuelto"

        examen_json["resuelto"] = resuelto
        examen_json = json.dumps(examen_json)

        if formato=="zip":
            tarea = self.creador.lanzar_tarea(request, "json2latex",
                                              data=examen_json, formato="zip")
        elif formato=="tgz":
            tarea = self.creador.lanzar_tarea(request, "json2latex",
                                              data=examen_json, formato="tgz")
        elif formato=="pdf":
            tarea = self.creador.lanzar_tarea(request, "json2pdf",
                                              data=examen_json, formato="pdf")
        else:
            # Retornamos la versión JSON
            headers = {"Content-type": "application/json",
                       "Content-disposition": 'attachment; filename="examen.json"'
                      }
            return morepath.Response(body=examen_json,
                                     status=200, headers=headers)
        if tarea is None:
            raise HTTPNotFound("Tipo de descarga no disponible")
        if not sync:
            return {
                "status": "Procesando",
                "link": request.link(tarea)
            }
        # esperar a que acabe la tarea y retornar el resultado
        wait = 0.1
        while wait<30:
            estado = request.view(tarea)
            if estado["status"] == "Completada":
                break
            time.sleep(wait)
            wait*=2
        if estado["status"] != "Completada":
            raise HTTPInternalServerError("No se pudo completar la tarea de compilación")
        resultado = request.view(tarea, name="download")
        tarea.delete()
        return resultado

with App.json(model=model.Asignatura) as view:
    @view(permission=EstarRegistrado)
    def view_asignatura(self, request):
        """Obtener JSON con datos de una asignatura"""
        return {
            "id": self.id,
            "nombre": self.nombre,
            "titulacion": self.titulacion,
        }

with App.json(model=model.Circulo) as view:
    @view(name="min", permission=SerPropietario)
    def view_circulo_min(self, request):
        """Obtener JSON con los datos mínimos de un círculo"""
        return {
            "id": self.id,
            "nombre": self.nombre,
        }

    @view(permission=SerPropietario)
    def view_circulo(self, request):
        """Obtener JSON con los datos de un círculo y sus miembros"""
        return {
            "id": self.id,
            "nombre": self.nombre,
            "creador": request.view(self.creador, name="min"),
            "miembros": [request.view(m, name="min") for m in self.miembros]
        }

    @view(name="full", permission=SerPropietario)
    def view_circulo_full(self, request):
        """Obtener JSON con los datos de un círculo, sus miembros y los problemas
        que se comparten con ese círculo"""
        return {
            "id": self.id,
            "nombre": self.nombre,
            "fecha_creacion": datetime_encode(self.fecha_creacion),
            "fecha_modificacion": datetime_encode(self.fecha_modificacion),
            "creador": request.view(self.creador, name="min"),
            "miembros": [request.view(m, name="min") for m in self.miembros],
            "problemas": [request.view(p, name="min") for p in self.problemas_visibles]
        }

    @view(request_method="DELETE", permission=SerPropietario)
    def delete_circulo(self, request):
        """Eliminar un círculo"""
        circulos = coll.Circulos()
        if circulos.delete_object(self.id) is None:
            return None
        return morepath.Response(status=204)

    @view(request_method="PUT", permission=SerPropietario)
    def update_circulo(self, request):
        """Actualizar datos de un círculo. Sólo se puede cambiar su nombre"""
        self.update(request.json)
        return request.view(self)

    @view(name="miembros", permission=SerPropietario)
    def view_circulo_profesores(self, request):
        """Obtener la lista de profesores que están en ese círculo"""
        return {
            "id": self.id,
            "miembros": [request.view(m, name="min") for m in self.miembros],
        }

    @view(name="miembros", request_method="POST", permission=SerPropietario)
    def add_profesores_to_circulo(self, request):
        """Añadir profesores a este círculo"""
        self.add_profesores(request.json)
        return request.view(self, name="miembros")

    @view(name="miembros", request_method="DELETE", permission=SerPropietario)
    def delete_profesores_from_circulo(self, request):
        """Eliminar profesores a este círculo"""
        self.remove_profesores(request.json)
        return request.view(self, name="miembros")

    @view(name="problemas", permission=SerPropietario)
    def view_circulo_problemas(self, request):
        """Obtener la lista de problemas que están compartidos con este círculo"""
        return {
            "id": self.id,
            "problemas": [request.view(p, name="min") for p in self.problemas_visibles]
        }

    @view(name="problemas", request_method="POST", permission=SerPropietario)
    def add_problemas_to_circulo(self, request):
        """Añadir problemas a este círculo"""
        self.add_problemas(request)
        return request.view(self, name="problemas")

    @view(name="problemas", request_method="DELETE", permission=SerPropietario)
    def delete_problemas_from_circulo(self, request):
        """Eliminar problemas de este círculo"""
        self.remove_problemas(request)
        return request.view(self, name="problemas")


#============================ COLECCIONES =====================================
with App.json(model=coll.DBCollection) as view:
    @view(permission=EstarRegistrado)
    def view_items(self, request):
        "Obtener listado de items"
        return [request.view(i, name="min") for i in self.query()]

    @view(name="full", permission=EstarRegistrado)
    def view_items_full(self, request):
        "Obtener listado de items expandido"
        return [request.view(i, name="full") for i in self.query()]

with App.json(model=coll.Profesores) as view:
    @view(request_method='POST', permission=SerAdmin)
    def add_item(self, request):
        "Añadir profesor nuevo a la lista"
        profe = self.add(request.json)

        @request.after
        def after(response): # pylint: disable=unused-variable
            """Cambia el status code"""
            response.status = 201

        return request.view(profe)

    @view(permission=EstarRegistrado)
    def view_items(self, request):
        "Obtener listado de profesores, pero no ves a los admin a menos que seas uno"
        quien = model.Profesor.get(id=request.identity.id)
        if quien.role=="admin":
            return [request.view(i) for i in self.query()]
        else:
            return [request.view(i, name="min") for i in self.query() if i.role=="profesor"]

with App.json(model=coll.Problemas) as view:
    @view(request_method='POST', permission=EstarRegistrado)
    def add_problema(self, request):
        "Añadir problema nuevo a la lista"
        quien = model.Profesor.get(id=request.identity.id)
        datos_problema = request.json
        datos_problema.update(creador={"email": quien.email})
        problema = self.add(datos_problema)

        @request.after
        def after(response): # pylint: disable=unused-variable
            """Cambia el status de la respuesta"""
            response.status = 201

        return request.view(problema)

    @view(name="mios", permission=EstarRegistrado)
    def get_created_problems(self, request):
        """Obtener la lista de problemas que este profesor ha creado"""
        # return [request.view(i, name="min") for i in self.get_created_by_user()]
        return [i.id for i in self.get_created_by_user(request.identity.id)]

    @view(permission=EstarRegistrado)
    def get_visible_problems(self, request):
        """Obtener la lista de problemas que este profesor puede ver"""
        return [request.view(i, name="min")
                for i in self.get_visible_by_user(request.identity.id)]

    @view(name="full", permission=EstarRegistrado)
    def get_visible_problems_full(self, request):
        """Obtener la lista de problemas que este profesor puede ver"""
        return [request.view(i, name="full")
                for i in self.get_visible_by_user(request.identity.id)]

with App.json(model=coll.Circulos) as view:
    @view(permission=EstarRegistrado)
    def get_circulos_creados(self, request):
        """Obtener la lista de círculos creados por este profesor"""
        return [request.view(i, name="min")
                for i in self.get_created_by_user(request.identity.id)]

    @view(name="full", permission=EstarRegistrado)
    def get_circulos_creados_full(self, request):
        """Obtener la lista de círculos creados por este profesor"""
        return [request.view(i, name="full")
                for i in self.get_created_by_user(request.identity.id)]

    @view(request_method='POST', permission=EstarRegistrado)
    def add_circulo(self, request):
        "Añadir un nuevo círculo"
        quien = model.Profesor.get(id=request.identity.id)
        datos_circulo = request.json
        datos_circulo.update(creador={"email": quien.email})
        circulo = self.add(datos_circulo)

        @request.after
        def after(response): # pylint: disable=unused-variable
            """Cambia el status de la respuesta"""
            response.status = 201

        return request.view(circulo)

with App.json(model=coll.Examenes) as view:
    @view(permission=EstarRegistrado)
    def get_examenes_creados(self, request):
        """Obtener la lista de exámenes creados por este profesor"""
        return [request.view(i, name="min")
                for i in self.get_created_by_user(request.identity.id)]

    @view(name="full", permission=EstarRegistrado)
    def get_examenes_creados_full(self, request):
        """Obtener la lista de exámenes creados por este profesor"""
        return [request.view(i, name="full")
                for i in self.get_created_by_user(request.identity.id)]

    @view(request_method='POST', permission=EstarRegistrado)
    def add_examen(self, request):
        "Añadir examen nuevo a la base de datos"
        quien = model.Profesor.get(id=request.identity.id)
        datos_examen = request.json
        datos_examen.update(creador={"email": quien.email})
        if "intro" not in datos_examen:
            datos_examen.update(intro="")
        examen = self.add(datos_examen)

        @request.after
        def after(response): # pylint: disable=unused-variable
            """Cambia el status de la respuesta"""
            response.status = 201

        return request.view(examen)

with App.json(model=coll.SubCollection) as view:
    @view(permission=SerPropietario)
    def get_circulo_miembros(self, request):
        """Obtener la lista de profesores o problemas en el círculo"""
        if self.full:
            return [request.view(p, name="min") for p in sorted(self.query())]
        else:
            return sorted([
                m.id for m in self.query()
            ])

    @view(request_method="POST", permission=SerPropietario)
    def post_circulo_miembros(self, request):
        """Añadir un profesor al círculo"""
        self.add_element(request)
        return request.view(self)

    @view(request_method="DELETE", permission=SerPropietario)
    def delete_circulo_miembros(self, request):
        """Eliminar un profesor del círculo"""
        self.remove_element(request)
        return request.view(self)

with App.json(model=coll.ExamenProblemas) as view:
    @view(permission=SerPropietario)
    def get_examen_problemas(self, request):
        """Obtener la lista de problemas en el examen, correctamente ordenados"""
        lista_problemas = [
                m.problema_id for m in self.query().order_by(model.Problema_examen.posicion)
            ]
        if self.full:
            return [request.view(p, name="min") for p in lista_problemas]
        else:
            return [p.id for p in lista_problemas]

with App.json(model=coll.Tags) as view:
    @view(name="visibles", permisions=EstarRegistrado)
    def get_mis_tags(self, request):
        """Obtener la lista de tags en problemas visibles por este profesor"""
        mis_tags = [p.tags for p in coll.Problemas().get_visible_by_user(request.identity.id)]
        flat = [ tag.name for conjunto in mis_tags for tag in conjunto ]
        return Counter(flat)

#=================== EXCEPCIONES, ERRORES ======================================
# Una vista JSON para cualquier excepción que se genere en el servidor
# Retorna un código 500 y un JSON con información de la excepción

# pylint:disable=invalid-name, unused-variable

@App.json(model=ObjectNotFound)
def view_ObjectNotFound(self, request):
    """Retornar 404 y json con debug info ante un objeto no encontrado en la base de datos"""
    @request.after
    def change_code(r):
        """Cambia status de la respuesta"""
        r.status = 404
        r.headers.add('Access-Control-Allow-Origin', '*')

    return {"debug": str(self)}

@App.json(model=HTTPNotFound)
def view_HTTPNotFound(self, request):
    """Retornar 404 y json con debug info ante una ruta no encontrada en la app"""
    @request.after
    def change_code(r):
        """Cambia status de la respuesta"""
        r.status = 404
        r.headers.add('Access-Control-Allow-Origin', '*')

    return {"debug": str(self)}

@App.json(model=TypeError)
def view_TypeError(self, request):
    """Retornar 422 y json con debug info ante parámetros mal formados"""
    @request.after
    def change_code(r):
        """Cambia status de la respuesta"""
        r.status = 422
        r.headers.add('Access-Control-Allow-Origin', '*')

    return {"debug": str(self)}

@App.json(model=ValueError)
def view_ValueError(self, request):
    """Retornar 422 y json con debug info ante valores erróneos"""
    @request.after
    def change_code(r):
        """Cambia status de la respuesta"""
        r.status = 422
        r.headers.add('Access-Control-Allow-Origin', '*')

    return {"debug": str(self)}

@App.json(model=HTTPForbidden)
def view_HTTPForbidden(self, request):
    """Retornar 403 y json con debug info ante fallo de autenticación"""
    @request.after
    def change_code(r):
        """Cambia status de la respuesta"""
        r.status = 403
        r.headers.add('Access-Control-Allow-Origin', '*')

    return {"debug": str(self)}

@App.json(model=HTTPUnauthorized)
def view_HTTPForbidden(self, request):
    """Retornar 401 y json con debug info ante fallo de autenticación"""
    @request.after
    def change_code(r):
        """Cambia status de la respuesta"""
        r.status = 401
        r.headers.add('Access-Control-Allow-Origin', '*')

    return {"debug": str(self)}


# =============================== CORS ===========================================
@App.tween_factory()
def cors_tween(app, handler):
    def cors_handler(request):
        # print(request)
        preflight = request.method == 'OPTIONS'
        if preflight:
            response = Response()
        else:
            response = handler(request)
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE')
        response.headers.add('Access-Control-Allow-Headers', 'authorization, content-type')
        return response
    return cors_handler


# ========================== REINICIO DE LA BASE DE DATOS =========================================
#
# Reseteo de la base de datos. Todo es un HORRIBLE HACK que habrá que quitar antes
# de enviar a producción.
#
# La idea de este endpoint es tenerlo como opción de emergencia para restaurar la
# base de datos a un estado "bien conocido", cuando no hay opción de entrar por ssh
# en la máquina del servidor para hacerlo "a mano" (lo que consistiría en parar el servidor,
# borrar el fichero mysql, crear uno nuevo con el script crear_base_de_datos.py, y
# poner de nuevo en marcha el servidor)
#
# En casos tales como cuando el servidor está funcionando en Heroku, hacer lo anterior no
# es posible. Por eso, suministro este endpoint de emergencia. Consiste en hacer:
#
#  POST /database_reset
#
# Y toda la base de datos será borrada y sustituída por la BD de ejemplo
#
# Ese endpoint está desprotegido (para de ese modo resetear también todas las contraseñas
# a sus valores por defecto), por lo que su mera existencia es un gran agujero de seguridad
#
# La implementación, además, también es horrible, debido a que todas las vistas morepath
# se ejecutan dentro de un entorno db_session, lo cual en general está bien y es muy cómodo
# porque hasta que no se salga de ese entorno no se hará el commit() a la base de datos,
# permitiendo por tanto una atomicidad en las operaciones que hagan las vistas. Pero tiene
# el inconveniente de que dentro de una db_session no se pueden borrar las tablas de la
# base de datos para volver a crearlas, lo que justamente es lo que necesito hacer.
#
# Después de darle vueltas, sólo se me ocurrió la siguiente solución. Consiste en envolver
# TODAS las llamadas a las vistas en mi propia función (reset_database_factory, más abajo)
# y dentro de ella invocar el manejo normal de la petición (lo cual por debajo instanciará
# el contexto db_session, procesará la invocación, cerrará ese contexto, y volverá a mi función)
# Una vez procesada toda la petición y de vuelta en mi función, miro si la respuesta final
# es la cadena "OK. Base de datos restaurada" y entonces en ese momento borro todas las tablas
# y creo los nuevos datos. Puedo hacerlo ahora porque ya salí de la db_session.
@App.json(model=appmodel.ResetDB, request_method="POST")
def view_reset_database(self, request):
    """Restaura la base de datos a una lista de problemas y profesores de ejemplo"""
    # A pesar de la respuesta, en realidad no ha borrado nada
    # Esta respuesta es la señal para que el tween que envuelve a todas las llamadas, lo haga
    if getattr(request.app.settings, "reset_database", None) is None:
        allow = True
    else:
        allow = request.app.settings.reset_database.allow
        print("Atributo:", allow)
    if allow:
        return "OK. Base de datos restaurada"
    else:
        raise HTTPForbidden("Opción inhabilitada")

# Y este es el tween en cuestión, que envuelve a pony_tween_factory del módulo more.pony
# que es el que crea el db_session alrededor de cada vista
@App.tween_factory(over=more.pony.app.pony_tween_factory)
def reset_database_factory(app, handler):
    # La siguiente función se ejecutará para cada petición a una vista
    def reset_database_maybe(request):
        # Invoca el manejador "normalmente"
        result = handler(request)
        # Si detecta que se ejecutó la vista view_reset_database, borra la base de datos
        if result.body == b'"OK. Base de datos restaurada"':
            model.db.drop_all_tables(with_all_data=True)
            model.db.create_tables()
            crear_db_ejemplo(model.db)
        return result
    return reset_database_maybe
