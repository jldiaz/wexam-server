import json
import time
from datetime import datetime
import morepath
import wexam
import yaml
import pytest

from webtest import TestApp as Client
import wexam.mixins
import wexam.model
from wexam.model import (db, Profesor, Cuestion, Examen, Problema, Problema_examen,
                         Asignatura, Tag, Circulo)
from crear_db_ejemplo import crear_db_ejemplo
from pony.orm import db_session
from passlib.hash import bcrypt
import jwt

# Aunque he intentado encapsular los test en clases, el objeto db, que
# representa la base de datos es global. No obstante, cada clase re-creará
# las tablas al arrancar y las borrará todas al terminar


class TestWithMockDatabaseUnlogged:
    """Las clases que hereden de esta no incluyen cabecera auth en sus peticiones
    por lo que emularán un cliente que aún no se ha logueado en el sistema"""
    def setup_class(self):
        # Preparamos una base de datos ficticia en memoria
        # Esta base de datos es compartida por todos los test, por los que
        # los test que cambien cosas afectan a los siguientes
        if db.provider is None:
            # El bind y generacion de map sólo debe hacerse una vez
            # y ya que db es una variable global hay que controlarlo aqui
            db.bind('sqlite', ':memory:', create_db=True)
            db.generate_mapping(create_tables=True)

            # La carga de la App también se hace una sola vez
            with open('settings/default.yaml') as config:
                settings_dict = yaml.load(config)
            wexam.App.init_settings(settings_dict)
            morepath.scan(wexam)
            morepath.commit(wexam.App)
        else:
            # Aún si la bd ya existía hay que volver a crear las tablas
            # porque el teardown las elimina
            db.create_tables()
        # y repoblar la base de datos
        crear_db_ejemplo(db)
        # self.c será el stub de cliente a través del cual hacer get/post/put..
        # a las rutas de la app (véanse los diferentes test)
        self.c = Client(wexam.App())
        # self.c = Client(app)

    def teardown_class(self):
        # Cuando todos los métodos-test de la clase hayan sido ejecutados
        # se ejecutará éste último, que eliminará todas las tablas de la
        # base de datos
        db.drop_all_tables(with_all_data=True)
        self.c = None


class TestWithMockDatabaseLoggedAsAdmin(TestWithMockDatabaseUnlogged):
    """Las clases que hereden de esta incorporarán ya en todas sus peticiones
    una cabecera auth que identifica al cliente como admin@example.com,
    que tiene rol de admin dentro de la app"""
    def setup_class(self):
        # Primero crear la base de datos e instanciar el cliente
        TestWithMockDatabaseUnlogged.setup_class(self)
        # Segundo, hacer login con unas credenciales válidas para poder
        # después probar el resto de la API
        respuesta = self.c.post_json('/login',
                                     {'email': 'admin@example.com',
                                      'password': '0000'})
        assert respuesta.status_code == 200
        jwt = respuesta.headers['Authorization']
        self.c.authorization = tuple(jwt.split())


class TestWithMockDatabaseLoggedAsProfesor(TestWithMockDatabaseUnlogged):
    """Las clases que hereden de esta incorporarán ya en todas sus peticiones
    una cabecera auth que identifica al cliente como un usuario,
    que tiene rol de profesor dentro de la app"""
    def setup_class(self):
        """Prepara los jwt de diferentes usuarios para usarlos cuando
        sea necesario"""
        # Primero crear la base de datos e instanciar el cliente
        TestWithMockDatabaseUnlogged.setup_class(self)

        # Segundo, hacer login con unas credenciales válidas para poder
        # después probar el resto de la API
        self.jwts = dict()
        for user in ("jldiaz@uniovi.es", "javier@uniovi.es", "marco@uniovi.es",
                     "joaquin@uniovi.es", "arias@uniovi.es", "admin@example.com"):
            respuesta = self.c.post_json(
                '/login', {'email': user,
                'password': '0000'})
            assert respuesta.status_code == 200
            jwt = respuesta.headers['Authorization']
            self.jwts[user.split("@")[0]] = tuple(jwt.split())

    def update_jwt_token(self, user):
        if not user:
            user="jldiaz"
        self.c.authorization = self.jwts[user]

    def get_as(self, *args, user=None, **kwargs):
        self.update_jwt_token(user)
        return self.c.get(*args, **kwargs)

    def post_as(self, *args, user=None, **kwargs):
        self.update_jwt_token(user)
        return self.c.post_json(*args, **kwargs)

    def put_as(self, *args, user=None, **kwargs):
        self.update_jwt_token(user)
        return self.c.put_json(*args, **kwargs)

    def delete_as(self, *args, user=None, **kwargs):
        self.update_jwt_token(user)
        return self.c.delete_json(*args, **kwargs)


class TestLogin(TestWithMockDatabaseUnlogged):
    """Comprobar el funcionamiento correcto del login"""
    def test_login_invalid_data_is_rejected(self):
        "Se rechaza un login que no incluya JSON válido"
        respuesta = self.c.post_json('/login',
                                     {'foo': 'bar'},
                                     expect_errors=True)
        assert respuesta.status_code == 422

    def test_login_invalid_user_is_rejected(self):
        "Se rechaza un login cuyo email no esté en la base de datos"
        respuesta = self.c.post_json('/login',
                                     {'email': 'nadie@nowhere.com'},
                                     expect_errors=True)
        assert respuesta.status_code == 401

    def test_login_missing_password_is_rejected(self):
        "Se rechaza un login si no incluye la password"
        respuesta = self.c.post_json('/login',
                                     {'email': 'jldiaz@uniovi.es'},
                                     expect_errors=True)
        assert respuesta.status_code == 401

    def test_login_invalid_password_is_rejected(self):
        "Se rechaza un login si la contraseña no es la almacenada"
        respuesta = self.c.post_json('/login',
                                     {'email': 'jldiaz@uniovi.es',
                                      'password': 'contraseñamala'},
                                     expect_errors=True)
        assert respuesta.status_code == 401

    def test_login_all_valid_returns_jwt_token(self):
        """Se admite un login con email y contraseña válidos, y la respuesta
        del servidor contiene una cabecera 'Authorization' con un token JWT"""
        respuesta = self.c.post_json('/login',
                                     {'email': 'jldiaz@uniovi.es',
                                      'password': '0000'},
                                     expect_errors=True)
        assert respuesta.status_code == 200
        assert "Authorization" in respuesta.headers
        auth_type, token = respuesta.headers["Authorization"].split()
        assert auth_type == "JWT"

        # Desciframos el token para ver que contiene información correcta
        claims = jwt.decode(token, verify=False)
        assert "sub" in claims
        assert "nombre" in claims
        assert "role" in claims
        assert claims["sub"] == "jldiaz@uniovi.es"
        assert claims["role"] == "profesor"


class TestRootPathAdminLogged(TestWithMockDatabaseLoggedAsAdmin):
    """Comprueba que se permite acceso a ruta / por un usuario logueado
    como admin"""
    def test_root(self):
        "Se permite acceso a ruta raiz"
        root = self.c.get('/')
        assert root.status_code == 200
        assert root.json.keys() == set([
            'examenes', 'problemas', 'profesores', 'tags', 'circulos'])

        # Comprobemos que las rutas devueltas son accesibles
        for path in root.json.values():
            result = self.c.get(path)
            assert result.status_code == 200


def verificar_timestamps(hace_poco, hace_mas):
    formato = "%Y%m%dT%H%M%S"
    ahora = datetime.now()
    antes = datetime.strptime(hace_poco, formato)
    mucho_antes = datetime.strptime(hace_mas, formato)
    assert antes > mucho_antes
    assert ahora > antes
    assert antes > mucho_antes


# Todos los test restantes se hacen tras haberse logueado como Admin
# pues de lo contrario fallarían. Es necesario rehacerlos para probar
# que los permisos se gestionan correctamente si no eres admin.
class TestProfesorDesdeAdmin(TestWithMockDatabaseLoggedAsAdmin):
    """Prueba operaciones sobre la entidad Profesor"""

    def test_get_profesor_by_id(self):
        "Comprobando profesores de ejemplo"

        # Este existe
        p1 = self.c.get('/profesor/1')
        assert p1.status_code == 200
        assert p1.json["nombre"] == "Jose Luis Díaz"

        # Este también
        p2 = self.c.get('/profesor/2')
        assert p2.status_code == 200
        assert p2.json["email"] == "marco@uniovi.es"

        # Este no, debe devolver 404
        p3 = self.c.get('/profesor/23', expect_errors=True)
        assert p3.status_code == 404

    def test_put_datos_profesor(self):
        "Probar a cambiar el email de uno"

        # Modificar el email de jl
        p1 = self.c.get('/profesor/1')
        assert p1.json["email"] == 'jldiaz@uniovi.es'
        creado = p1.json["fecha_creacion"]
        modificado = p1.json["fecha_modificacion"]
        p1 = self.c.put_json('/profesor/1', {'email': 'jldiaz@gmail.com'})
        assert p1.json["email"] == 'jldiaz@gmail.com'
        # Volver a dejarlo como estaba
        p1 = self.c.put_json('/profesor/1', {'email': 'jldiaz@uniovi.es'})
        assert p1.json["email"] == 'jldiaz@uniovi.es'

        # Verificar que ha cambiado la fecha de modificación pero no la de creación
        assert creado == p1.json["fecha_creacion"]
        assert modificado < p1.json["fecha_modificacion"]
        verificar_timestamps(p1.json["fecha_modificacion"], p1.json["fecha_creacion"])

    def test_put_mal_datos_profesor(self):
        "Enviar datos incorrectos como parte del PUT"

        # De momento ocurre una excepción no manejada en el servidor ante
        # un dato inválido que la BBDD no espera. Eso se traduce en un
        # status 500 para el cliente.
        #
        # En el futuro habrá que manejar correctamente esto en el servidor
        # y enviar al cliente un código de estado 422 (Unprocessable entity)
        p1 = self.c.put_json('/profesor/1', {'campo_no_valido': "valor"},
                             expect_errors=True)
        assert p1.status_code == 422

        p1 = self.c.put_json('/profesor/1', {'email': True},   # Tipo no válido
                             expect_errors=True)
        assert p1.status_code == 422

    def test_get_lista_profesores(self):
        """Comprobar que un GET de la lista obtiene el número apropiado
        de elementos"""
        # Mirar cuántos profesores hay
        todos = self.c.get('/profesores')
        assert len(todos.json) == 6

    def test_post_profesor_nuevo(self):
        "Probar un POST a la lista"

        todos = self.c.get('/profesores')
        len_antes = len(todos.json)
        # Añadir otro profesor
        p3 = self.c.post_json('/profesores',
                              {'nombre': 'A. Nónimo',
                               'email': 'nadie@example.com',
                               'password': '1234',
                               'role': 'guest'})
        # Comprobar respuesta
        assert p3.status_code == 201
        esperado = {'nombre': 'A. Nónimo',
                    'email': 'nadie@example.com',
                    'role': 'guest'}
        # La respuesta contiene además el id, por lo que no puedo
        # comparar la igualdad. Pero puedo mirar si lo que espero
        # forma parte (issubset) de lo que recibo
        assert set(esperado.items()).issubset(p3.json.items())

        # Mirar cuántos profesores hay
        todos = self.c.get('/profesores')
        assert len(todos.json) == len_antes + 1

    def test_post_nueva_password_almacenada(self):
        """Comprobar que la contraseña de un nuevo profesor no es
        almacenada en claro"""
        # Verificar que se ha añadido
        # Mirar cuántos profesores hay
        p7 = self.c.get('/profesor/7')
        assert p7.status_code == 200
        assert p7.json["email"] == 'nadie@example.com'
        with db_session:
            # Comprobar que la contraseña no se almacena en claro
            assert Profesor[7].password != "1234"
            # Pero que es verificable
            assert bcrypt.verify("1234", Profesor[7].password)

    def test_put_cambia_password_almacenada(self):
        """Comprobar que un cambio de contraseña mediante PUT
        no la almacena en claro"""
        p7 = self.c.get('/profesor/7')
        assert p7.status_code == 200
        assert p7.json["email"] == 'nadie@example.com'

        time.sleep(1)
        p7 = self.c.put_json('/profesor/7', {'password': '0000'})
        assert p7.status_code == 200

        verificar_timestamps(p7.json["fecha_modificacion"], p7.json["fecha_creacion"])

        # Mirar en la base de datos a ver qué se ha guardado
        with db_session:
            # Comprobar que la contraseña no se almacena en claro
            assert Profesor[7].password != "0000"
            # Pero que es verificable
            assert bcrypt.verify("0000", Profesor[7].password)

    def test_delete_profesor_removes_it_from_circle(self):
        """Un profesor existente se elimina correctamente
        y desaparece de los círculos en que estaba."""

        # Obtengo primero todos los profesores
        todos = self.c.get('/profesores')
        len_antes = len(todos.json)

        # Obtengo los que hay en el círculo 2 (que contiene a joaquin y marco)
        circulo = self.c.get('/circulo/2')
        assert circulo.status_code == 200
        assert len(circulo.json['miembros']) == 2

        # Vamos a eliminar a joaquin
        joaquin = self.c.get('/profesor/3')
        assert joaquin.json['nombre'] == 'Joaquín Entrialgo'

        result = self.c.delete('/profesor/3')
        assert result.status_code == 204

        # Si fue eliminado correctamente deberá haber un profesor menos
        todos = self.c.get("/profesores")
        len_despues = len(todos.json)
        assert len_despues == len_antes - 1

        # Además el profesor 3 ya no está accesible
        joaquin = self.c.get('/profesor/3', expect_errors=True)
        assert joaquin.status_code == 404

        # Y el círculo de que formaba parte, ya no le contiene
        circulo = self.c.get('/circulo/2')
        assert circulo.status_code == 200
        assert len(circulo.json['miembros']) == 1

    def test_delete_profesor_removes_created_content(self):
        """Al eliminar un profesor desaparecen los círculos y problemas que él había creado"""

        # Asegurarse de que jose es el usuario /1
        jose = self.c.get("/profesor/1")
        assert jose.json["email"] == 'jldiaz@uniovi.es'

        # Mirar todos los problemas, círculos y exámenes antes de borrar a ese usuario
        problemas_antes = self.c.get("/problemas")
        circulos_antes = self.c.get("/circulos")
        examenes_antes = self.c.get("/examenes")
        # Tiene que haber 4 problemas y 2 círculos creados por ese usuario
        cuantos_jose = len([ex for ex in problemas_antes.json
                                      if 'Jose'  in ex['creador']['nombre']])
        assert cuantos_jose == 4
        assert len(circulos_antes.json) == 2        # Antes de borrar a jose hay dos circulos

        # Borramos al usuario
        result = self.c.delete('/profesor/1')
        assert result.status_code == 204

        # Comprobamos que también desaparece el contenido creado por él
        problemas_despues = self.c.get("/problemas")
        circulos_despues = self.c.get("/circulos")
        examenes_despues = self.c.get("/examenes")

        # Debe haber cuatro problemas menos
        assert len(problemas_despues.json) == len(problemas_antes.json) - cuantos_jose

        # Debe haber dos círculos menos
        assert len(circulos_despues.json) == 0

        # En cambio no había exámenes de jose
        assert examenes_antes.json == examenes_despues.json

    def test_delete_profesor_inexistente(self):
        """El intento de eliminar un profesor no existente es ignorado"""
        todos = self.c.get('/profesores')
        len_antes = len(todos.json)
        result = self.c.delete('/profesor/100', expect_errors=True)
        assert result.status_code == 404

        todos = self.c.get("/profesores")
        len_despues = len(todos.json)
        assert len_despues == len_antes


class TestExamenDesdeAdmin(TestWithMockDatabaseLoggedAsAdmin):
    """Prueba operaciones sobre la entidad Examen"""
    def test_get_lista_examenes_tiene_un_elemento(self):
        """Comprobar que la lista de examenes tiene un elemento"""
        examenes = self.c.get("/examenes")
        assert examenes.status_code == 200
        assert len(examenes.json) == 2
        examen = examenes.json[0]
        campos_esperados = set(['estado', 'asignatura', 'titulacion', 'convocatoria',
                                'creador', 'fecha', 'tipo', 'id', 'publicado'])
        assert campos_esperados == set(examen.keys())

    def test_get_lista_de_examenes_retorna_vista_minima_de_cada_examen(self):
        examenes = self.c.get("/examenes")
        assert examenes.status_code == 200
        examen = self.c.get("/examen/1/min")
        assert examen.status_code == 200
        assert examen.json == examenes.json[0]

    def test_vista_minima_de_examen_tiene_campos_correctos(self):
        """Comprobar que la vista mínima de un examen tiene los
        atributos esperados"""
        examen = self.c.get("/examen/1/min")
        assert examen.status_code == 200
        campos_esperados = set(['estado' ,'asignatura', 'titulacion', 'convocatoria',
                                'creador', 'fecha', 'tipo', 'id', 'publicado'])
        assert campos_esperados == set(examen.json.keys())

    def test_vista_normal_examen_contiene_campos_correctos(self):
        """Comprobar que la vista por defecto de un examen tiene los
        atributos esperados"""
        examen = self.c.get("/examen/1")
        assert examen.status_code == 200
        campos_esperados = set(['estado', 'asignatura', 'titulacion', 'convocatoria',
                                'creador', 'fecha', 'tipo', 'intro', 'problemas', 'id',
                                'publicado'])
        assert campos_esperados == set(examen.json.keys())

        # Además, cada problema ha tener los campos de la vista mínima
        for p in examen.json["problemas"]:
            p_min = self.c.get("/problema/{}/min".format(p["id"]))
            assert p_min.status_code == 200
            assert set(p_min.json.keys()) == set(p.keys())

    def test_post_examen_correcto(self):
        """Se puede crear un examen cuando se le pasan los campos correctos"""
        datos = {
                    "id": "Esto será ignorado",
                    "creador": "Esto será ignorado",
                    "problemas": [ "Esto será ignorado" ],
                    "asignatura": "Sistemas Distribuidos",
                    "titulacion": "Informática",
                    "convocatoria": "Enero",
                    "estado": "abierto",
                    "fecha": "20180517",
                    # "intro": "Blah, blah",
                    "tipo": "A"
                }
        result = self.c.post_json("/examenes", datos)
        assert result.status_code == 201
        assert result.json["creador"]["nombre"] == "Administrador"
        assert result.json["convocatoria"] == "Enero"
        assert result.json["fecha"] == "20180517"
        assert result.json["estado"] == "abierto"
        id_examen = result.json["id"]

        # Comprobar que aparece en la lista de examenes
        result = self.c.get("/examenes")
        assert result.status_code == 200
        assert len(result.json) == 3
        assert id_examen in [e["id"] for e in result.json]

        # Comprobar que tiene marcas de tiempo
        result = self.c.get("/examen/{}/full".format(id_examen))
        assert result.status_code == 200
        assert result.json["fecha_creacion"] == result.json["fecha_modificacion"]

    def test_post_examenes_incorrectos(self):
        """Comprobar los diferentes errores"""
        # No hay campos en el examen
        datos = {}
        result = self.c.post_json("/examenes", datos, expect_errors=True)
        assert result.status_code == 422

        datos_bien = {
                    "asignatura": {
                        "id": "1",
                    },
                    "convocatoria": "Enero",
                    "estado": "abierto",
                    "fecha": "20180517",
                    "intro": "Blah, blah",
                    "tipo": "A"
                }

        # La asignatura no es un diccionario
        datos_mal = datos_bien.copy()
        datos_mal.update(asignatura = [])
        result = self.c.post_json("/examenes", datos_mal, expect_errors=True)
        assert result.status_code == 422

        # El diccionario de la asignatura no tiene id
        datos_mal = datos_bien.copy()
        datos_mal.update(asignatura = { "nombre": "Sistemas Distribuidos"})
        result = self.c.post_json("/examenes", datos_mal, expect_errors=True)
        assert result.status_code == 422

        # El id de la asignatura no corresponde a ninguna asignatura
        datos_mal = datos_bien.copy()
        datos_mal.update(asignatura = { "id": "200"})
        result = self.c.post_json("/examenes", datos_mal, expect_errors=True)
        assert result.status_code == 422

        # No tiene fecha
        datos_mal = datos_bien.copy()
        del datos_mal["fecha"]
        result = self.c.post_json("/examenes", datos_mal, expect_errors=True)
        assert result.status_code == 422

        # La fecha no tiene un formato válido
        datos_mal = datos_bien.copy()
        datos_mal.update(fecha = "2018-05-14")
        result = self.c.post_json("/examenes", datos_mal, expect_errors=True)
        assert result.status_code == 422

        # No tiene intro
        datos_mal = datos_bien.copy()
        del datos_mal["intro"]
        result = self.c.post_json("/examenes", datos, expect_errors=True)
        assert result.status_code == 422

    def test_put_examen_abierto(self):
        """Modificar un examen abierto"""

        time.sleep(1)
        result = self.c.get("/examen/1")
        assert result.status_code == 200
        antes = result.json

        datos = {
                    "id": "Esto será ignorado",
                    "creador": "Esto será ignorado",
                    "problemas": [ "Esto será ignorado" ],
                    "asignatura": "Sistemas Distribuidos",
                    "titulacion": "Informática",
                    "convocatoria": "Julio",
                    #"estado": "abierto",
                    "fecha": "20180522",
                    "intro": "Esta es la típica introducción",
                    "tipo": "Z"
                }
        result = self.c.put_json("/examen/1", datos)
        assert result.status_code == 200
        # El autor no debe haber cambiado
        assert result.json["creador"]["nombre"] == antes["creador"]["nombre"]
        # Ni la lista de problemas
        assert result.json["problemas"] ==  antes["problemas"]
        # Ni el estado
        assert result.json["estado"] == antes["estado"]
        assert result.json["estado"] == "abierto"
        # Pero el resto si
        assert result.json["asignatura"] == datos["asignatura"]
        assert result.json["titulacion"] == datos["titulacion"]
        assert result.json["convocatoria"] == datos["convocatoria"]
        assert result.json["fecha"] == datos["fecha"]
        assert result.json["intro"] == datos["intro"]
        assert result.json["tipo"] == datos["tipo"]

        # Y la fecha actualizada
        result = self.c.get("/examen/1/full")
        assert result.status_code == 200
        verificar_timestamps(result.json["fecha_modificacion"], result.json["fecha_creacion"])

    def test_put_examen_mal(self):
        """Modificar un examen abierto, pero enviando malos datos"""
        # No hay campos en el put, no se modifica nada
        datos = {}
        result = self.c.put_json("/examen/1", datos, expect_errors=True)
        assert result.status_code == 200

        datos_bien = {
                    "asignatura": "Sistemas Distribuidos",
                    "titulacion": "Informática",
                    "convocatoria": "Enero",
                    #"estado": "abierto",
                    "fecha": "20180517",
                    "intro": "Blah, blah",
                    "tipo": "A"
                }

        # La asignatura no es un diccionario
        datos_mal = datos_bien.copy()
        datos_mal.update(asignatura = [])
        result = self.c.put_json("/examen/1", datos_mal, expect_errors=True)
        assert result.status_code == 422

        # El diccionario de la asignatura no tiene id
        datos_mal = datos_bien.copy()
        datos_mal.update(asignatura = { "nombre": "Sistemas Distribuidos"})
        result = self.c.put_json("/examen/1", datos_mal, expect_errors=True)
        assert result.status_code == 422

        # El id de la asignatura no corresponde a ninguna asignatura
        datos_mal = datos_bien.copy()
        datos_mal.update(asignatura = { "id": "200"})
        result = self.c.put_json("/examen/1", datos_mal, expect_errors=True)
        assert result.status_code == 422

        # No tiene fecha (no hay error, se actualizan los otros campos)
        datos_mal = datos_bien.copy()
        del datos_mal["fecha"]
        result = self.c.put_json("/examen/1", datos_mal, expect_errors=True)
        assert result.status_code == 200

        # La fecha no tiene un formato válido
        datos_mal = datos_bien.copy()
        datos_mal.update(fecha = "2018-05-14")
        result = self.c.put_json("/examen/1", datos_mal, expect_errors=True)
        assert result.status_code == 422

        # No tiene intro (no hay error, se actualizan los otros campos)
        datos_mal = datos_bien.copy()
        del datos_mal["intro"]
        result = self.c.put_json("/examen/1", datos_mal, expect_errors=True)
        assert result.status_code == 200

        # El estado del examen no debe haber cambiado
        assert result.json["estado"] == "abierto"

    def todo_test_put_examen_cerrado(self):
        """No se debe de poder modificar un examen no abierto"""

        datos = {
                    "id": "Esto será ignorado",
                    "creador": "Esto será ignorado",
                    "problemas": [ "Esto será ignorado" ],
                    "asignatura": {
                        "id": "2",
                    },
                    "convocatoria": "Julio",
                    "estado": "abierto",
                    "fecha": "20180522",
                    "intro": "Esta es la típica introducción",
                    "tipo": "Z"
                }
        result = self.c.put_json("/examen/2", datos, expect_errors = True)
        assert result.status_code == 422
        assert "El examen no puede modificarse por no estar abierto" in result.json["debug"]

    def test_delete_examen_sin_problemas(self):
        """Borrar un examen que no tenía problemas con éxito"""
        result = self.c.get("/examenes")
        assert result.status_code == 200
        # El último examen creado es el que tiene id más alto, ese será el que borremos
        ultimo_examen_id = max(ex["id"] for ex in result.json)

        result = self.c.delete("/examen/{}".format(ultimo_examen_id))
        assert result.status_code == 204

        # Verificar que ya no aparece en la lista de exámenes
        result = self.c.get("/examenes")
        assert result.status_code == 200
        ids_examenes = [ ex["id"] for ex in result.json ]
        assert ultimo_examen_id not in ids_examenes

        # Intentar recuperarlo dará un error "Not found"
        result = self.c.get("/examen/{}".format(ultimo_examen_id), expect_errors=True)
        assert result.status_code == 404

    def test_delete_examen_cerrado(self):
        """Un examen cerrado no debería poder borrarse"""
        result = self.c.get("/examen/2")
        assert result.status_code == 200
        assert result.json["estado"] != "abierto"

        # Intentar borrarlo dará error
        result = self.c.delete("/examen/2", expect_errors=True)
        assert result.status_code == 422
        assert 'El examen no puede borrarse por no estar abierto' in result.json["debug"]

        # Y no habrá sido borrado
        result = self.c.get("/examen/2")
        assert result.status_code == 200

    def test_añadir_problemas_a_examen(self):
        """Añadir dos problemas a un examen"""

        result = self.c.get("/examen/1/problemas")
        assert result.status_code == 200
        assert len(result.json["problemas"]) == 3

        # El examen 1 tiene 3 problemas, con ids 8, 9, 2
        for esperado, viene in zip([8,9,2], result.json["problemas"]):
            assert viene["id"] == esperado

        # Vamos a añadirle los problemas de ids 1, 2, 3
        lista_ids = []
        for id in [1,2,3]:
            lista_ids.append({"id": str(id)})
        result = self.c.post_json("/examen/1/problemas", {"problemas": lista_ids})
        assert result.status_code == 200

        # Como el 2 ya estaba en el examen, no será añadido
        assert len(result.json["problemas"]) == 5

        for esperado, viene in zip([8,9,2,1,3], result.json["problemas"]):
            assert viene["id"] == esperado

        # Verificar que se ha cambiado la marca de fecha
        result = self.c.get("/examen/1/full")
        assert result.status_code == 200
        verificar_timestamps(result.json["fecha_modificacion"], result.json["fecha_creacion"])

    def test_añadir_mal_problemas(self):
        """Intentos erróneos de añadir problemas, que deben generar error 422"""
        result = self.c.get("/examen/1/full")
        assert result.status_code == 200
        antes = result.json["fecha_modificacion"]

        result = self.c.get("/examen/1/problemas")
        assert result.status_code == 200
        assert len(result.json["problemas"]) == 5 # Como consecuencia del test anterior
        ids_problemas_antes = set(prob["id"] for prob in result.json["problemas"])

        # La lista contiene un problema inexistente
        bien = {"id": "5"}
        mal = {"id": "200"}
        result = self.c.post_json("/examen/1/problemas", {"problemas": [bien, mal]},
                                 expect_errors=True)
        assert result.status_code == 422
        assert "La lista de problemas a añadir contiene problemas no válidos" in result.json["debug"]

        # La lista contiene cosas que no son diccionarios
        mal = None
        result = self.c.post_json("/examen/1/problemas", {"problemas": [bien, mal]},
                                    expect_errors=True)
        assert result.status_code == 422
        assert "La lista de problemas no contiene objetos válidos" in result.json["debug"]

        mal = "cadena"
        result = self.c.post_json("/examen/1/problemas", {"problemas": [bien, mal]},
                                    expect_errors=True)
        assert result.status_code == 422
        assert "La lista de problemas no contiene objetos válidos" in result.json["debug"]

        # O contiene un diccionario, pero sin id
        mal = { "otra": "cosa" }
        result = self.c.post_json("/examen/1/problemas", {"problemas": [bien, mal]},
                                    expect_errors=True)
        assert result.status_code == 422
        assert "Los objetos problema no tienen campo id" in result.json["debug"]

        # O contiene un id, pero no numérico
        mal = { "id": "cosa" }
        result = self.c.post_json("/examen/1/problemas", {"problemas": [bien, mal]},
                                    expect_errors=True)
        assert result.status_code == 422
        assert "must be int" in result.json["debug"]

        # O contiene elementos duplicados
        mal = bien
        result = self.c.post_json("/examen/1/problemas", {"problemas": [bien, mal]},
                                    expect_errors=True)
        assert result.status_code == 422
        assert "La lista de problemas contiene elementos duplicados" in result.json["debug"]

        # Tras todos los errores, el examen sigue como estaba al principio
        result = self.c.get("/examen/1/problemas")
        assert result.status_code == 200
        assert len(result.json["problemas"]) == 5 # Como consecuencia del test anterior
        ids_problemas_despues = set(prob["id"] for prob in result.json["problemas"])
        assert ids_problemas_antes == ids_problemas_despues

        # Verificar que no ha cambiado su marca de fecha
        result = self.c.get("/examen/1/full")
        assert result.status_code == 200
        assert result.json["fecha_modificacion"] == antes

    def test_quitar_problemas_de_examen(self):
        """Quitar dos problemas de un examen"""

        result = self.c.get("/examen/1/problemas")
        assert result.status_code == 200
        assert len(result.json["problemas"]) == 5

        # El examen 1 tiene 3 problemas, con ids 8, 9, 2, 1, 3 (como consecuencia del test anterior)
        for esperado, viene in zip([8,9,2,1,3], result.json["problemas"]):
            assert viene["id"] == esperado

        # Vamos a quitarle los problemas de ids 1, 2, 3
        lista_ids = []
        for id in [1,2,3]:
            lista_ids.append({"id": str(id)})
        result = self.c.delete_json("/examen/1/problemas", {"problemas": lista_ids})
        assert result.status_code == 200

        # Comprobamos que los ha quitado
        assert len(result.json["problemas"]) == 2
        for esperado, viene in zip([8,9], result.json["problemas"]):
            assert viene["id"] == esperado

        # Y que los problemas en cuestión ya no figuran en ese examen
        for id in [1,2,3]:
            # Obtener la lista de exámenes en que aparece el problema
            result = self.c.get("/problema/{}/examenes".format(id))
            assert result.status_code == 200
            # Verificar que el examen/1 no está en esa lista
            ids_examenes = [id.split("/")[-1] for id in result.json["_links"]]
            assert 1 not in ids_examenes

        # Verificar que se ha cambiado la marca de fecha
        result = self.c.get("/examen/1/full")
        assert result.status_code == 200
        verificar_timestamps(result.json["fecha_modificacion"], result.json["fecha_creacion"])

    def test_borrar_examen_con_problemas(self):
        """Borrar un examen que tenía problemas asignados gestiona correctamente los problemas"""
        # Obtenemos el examen 1 para ver su lista de problemas
        result = self.c.get("/examen/1")
        assert result.status_code == 200
        ids_problemas = [ prob["id"] for prob in result.json["problemas"] ]
        # Comprobar que cada uno de esos problemas aparece como asignado a ese examen
        for problema in ids_problemas:
            # Obtener la lista de exámenes en que aparece el problema
            result = self.c.get("/problema/{}/examenes".format(problema))
            assert result.status_code == 200
            # Verificar que el examen/1 está en esa lista
            ids_examenes = [id.split("/")[-1] for id in result.json["_links"]]
            assert "1" in ids_examenes

        # Ahora borramos el examen de la bbdd
        result = self.c.delete("/examen/1")
        assert result.status_code == 204

        # Y comprobamos que los problemas de antes siguen existiendo, pero ya no están
        # asociados a ese examen
        for problema in ids_problemas:
            # Obtener la lista de exámenes en que aparece el problema
            result = self.c.get("/problema/{}/examenes".format(problema))
            assert result.status_code == 200
            # Verificar que el examen/1 no está en esa lista
            ids_examenes = [id.split("/")[-1] for id in result.json["_links"]]
            assert 1 not in ids_examenes


class TestAsignaturasExamenesDesdeAdmin(TestWithMockDatabaseLoggedAsAdmin):
    """Prueba la gestión de asignaturas asociadas a exámenes"""
    def test_modificar_asignatura_crea_nueva(self):
        """Modifica la asignatura asociada a un examen, creando una nueva"""
        datos = {
                    "asignatura": "Fundamentos de Informática",
                    "titulacion": "Química",
                }
        result = self.c.put_json("/examen/1", datos)
        assert result.status_code == 200

        # Tras el cambio en el examen, habrá una nueva asignatura en la base de datos
        with db_session:
            assert len(Asignatura.select()) == 2

    def test_modificar_asignatura_cambia(self):
        """Modifica la asignatura asociada a un examen, usando otra que ya había"""
        datos = {
                    "asignatura": "Fundamentos de Informática",
                    "titulacion": "Química",
                }
        result = self.c.put_json("/examen/1", datos)
        assert result.status_code == 200

        # Tras el cambio en el examen, sigue habiendo dos asignaturas
        with db_session:
            assert len(Asignatura.select()) == 2

    def test_modificar_asignatura_elimina(self):
        """Modifica la asignatura asociada a un examen, haciendo desaparecer una que había"""
        datos = {
                    "asignatura": "Sistemas Distribuidos",
                    "titulacion": "Informática",
                }
        result = self.c.put_json("/examen/1", datos)
        assert result.status_code == 200

        # Tras el cambio en el examen, desaparece la asignatura de Fundamentos, pues el único
        # examen que la tenía asociada era el 1
        with db_session:
            assert len(Asignatura.select()) == 1
            for a in Asignatura.select():
                assert a.nombre != "Fundamentos de Informática"


class TestProblemaDesdeAdmin(TestWithMockDatabaseLoggedAsAdmin):
    """Comprueba operaciones sobre la entidad Problema"""
    def test_get_lista_problemas(self):
        "Comprobando preguntas de ejemplo"
        c = self.c
        todos = c.get('/problemas')
        assert len(todos.json) == 10

        # Comprobemos que cada problema tiene un resumen y enunciado correcto
        for n in range(1, 11):
            p = c.get('/problema/%d' % n)
            assert p.json["resumen"] == ("Problema %d" % (n-1))
            assert p.json["enunciado"] == ("Enunciado general del problema %d"
                                           % (n-1))

        # Comprobemos los tags del primer problema
        esperados = ["sd", "sockets"]
        p = c.get("/problema/1")
        assert set(p.json["tags"]) == set(esperados)

    def test_get_problema_examenes(self):
        """Obtiene la lista de exámenes en la que está un problema"""
        c = self.c

        # Primero extraemos un examen, el de id=1
        exam = c.get("/examen/1")
        assert exam.status_code == 200

        id_exam = exam.json["id"]

        # Ahora recorremos la lista de problemas en ese examen y comprobamos
        # que en cada uno de ellos, la ruta /examenes devuelve una lista
        # que contiene al examen de id=1
        for prob in exam.json["problemas"]:
            prob_id = prob["id"]
            prob_exams = c.get("/problema/{}/examenes".format(prob_id))
            assert prob_exams.status_code == 200
            assert id_exam in prob_exams.json["examenes"]

    def test_tags_de_problemas_en_lista_tags(self):
        """Comprobar que todos los tags usados en los problemas
        aparecen en la lista de tags"""
        c = self.c
        tags = set(c.get("/tags").json)
        problemas = c.get('/problemas').json
        for p in problemas:
            assert set(p["tags"]).issubset(tags)
        # Comparar que la lista de tags que sale en la vista /problemas
        # coincide con la que muestra cada problema por separado
        for p in problemas:
            p_detail = c.get("/problema/{}".format(p["id"])).json
            assert set(p_detail["tags"]) == set(p["tags"])

    def test_post_problema_nuevo(self):
        """Comprobar que se puede crear un problema nuevo, dados los elementos
        apropiados"""
        json_a_enviar = """
            {
            "creador": {
                "email": "jldiaz@uniovi.es"
            },
            "cuestiones": [
                {
                "enunciado": "Primera pregunta, vale 2 puntos",
                "explicacion": "Y esta es la explicación",
                "posicion": 1,
                "puntos": 2,
                "respuesta": "Esta es la solución a la pregunta"
                },
                {
                "enunciado": "Segunda pregunta vale tres puntos",
                "explicacion": "Explicación de la segunda",
                "posicion": 2,
                "puntos": 3,
                "respuesta": "Solución de la segunda"
                },
                {
                "enunciado": "Esta es la tercera. Sin puntos. Sin explicación",
                "explicacion": "",
                "posicion": 3,
                "respuesta": "Esta es la solución"
                }
            ],
            "enunciado": "Enunciado general del problema añadido",
            "resumen": "Ejemplo añadido",
            "tags": [
                "sd",
                "ftp",
                "sftp"
            ]
        }
        """
        # Antes de añadir el problema, veamos cuántas cuestiones
        # tiene la base de datos
        with db_session:
            n_cuestiones_antes = Cuestion.select().count()
            n_problemas_antes = Problema.select().count()
            n_tags_antes = Tag.select().count()

        # Añadir problema y verificar que ha ido bien
        c = self.c
        prob = c.post("/problemas", params=json_a_enviar,
                      content_type="application/json")
        assert prob.status_code == 201

        # Comprobar ciertos totales
        assert len(prob.json["cuestiones"]) == 3
        assert prob.json["n_cuestiones"] == 3
        assert prob.json["puntos"] == 6

        # Tras añadirlo, el número de cuestiones y problemas
        # en la base de datos habrá crecido
        with db_session:
            n_cuestiones_despues = Cuestion.select().count()
            n_problemas_despues = Problema.select().count()
            n_tags_despues = Tag.select().count()

        assert n_cuestiones_despues == n_cuestiones_antes + 3
        assert n_problemas_despues == n_problemas_antes + 1

        # Los Tags habrán crecido en dos, pues uno de ellos ("sd")
        # ya era conocido y no debe registrarse de nuevo
        assert n_tags_despues == n_tags_antes + 2

        # Comprobar los tags del problema guardado
        assert set(["sd", "ftp", "sftp"]) == set(prob.json["tags"])

        # Comprobar que los nuevos tags están registrados en la bbdd
        lista_tags_en_db = c.get("/tags").json
        assert set(["ftp", "sftp"]).issubset(lista_tags_en_db)

        # Comprobar que el creador es el correcto
        # (NOTA: Aunque el json del problema que hemos enviado tenía un
        # autor, wexam ignora ese campo y lo sustituye por el usuario cuyo
        # id va en el JWT)
        assert prob.json["creador"]["nombre"] == "Administrador"

        # Comprobar que las cuestiones quedan almacenadas en el orden correcto
        enunciados_ordenados = [
            "Primera pregunta, vale 2 puntos",
            "Segunda pregunta vale tres puntos",
            "Esta es la tercera. Sin puntos. Sin explicación"
            ]
        for cuestion_id, enunciado_esperado in zip(
                prob.json["cuestiones"], enunciados_ordenados):
            cuestion = c.get(cuestion_id).json
            assert enunciado_esperado == cuestion["enunciado"]

        # Comprobar que tiene marcas de tiempo
        result = self.c.get("/problema/{}/full".format(prob.json["id"]))
        assert result.status_code == 200
        assert result.json["fecha_creacion"] == result.json["fecha_modificacion"]

    def test_get_problema_isdeletable(self):
        """Comprueba la API problema/<id>/isdeletable"""

        # En nuestra base de datos sólo dos un examenes.
        # El primero está abierto, el segundo cerrado. Sólo las
        # preguntas del segundo son "imborrables"
        resp = self.c.get("/examen/2")
        assert resp.status_code == 200
        assert resp.json["estado"] == "cerrado"
        preguntas_examen_cerrado = [p["id"] for p in resp.json["problemas"]]

        # Obtener todos los problemas de la bbdd
        resp = self.c.get("/problemas")
        assert resp.status_code == 200
        for problema in resp.json:
            r = self.c.get("/problema/{}/isdeletable".format(problema["id"]))
            assert r.status_code == 200
            if problema["id"] in preguntas_examen_cerrado:
                assert r.json["is_deletable"] == False
            else:
                assert r.json["is_deletable"] == True

    def test_delete_problema(self):
        """Eliminamos el problema anterior y comprobamos que desaparecen también
        sus cuestiones asociadas, y los tags que sólo existían para él"""

        c = self.c

        # Tomemos datos antes de eliminar el problema
        with db_session:
            n_problemas_antes = Problema.select().count()

        # Tomemos el id del último problema añadido, y de sus cuestiones
        problemas = c.get("/problemas")
        assert len(problemas.json) == n_problemas_antes

        ultimo_problema_id = problemas.json[-1]["id"]
        ultimo_problema = c.get("/problema/{}".format(ultimo_problema_id))
        assert ultimo_problema.json["resumen"] == "Ejemplo añadido"
        ultimas_cuestiones_ids = [id for id in
                                  ultimo_problema.json["cuestiones"]]

        # Verifiquemos que todas esas cuestiones existen en la bbdd
        for q_id in ultimas_cuestiones_ids:
            r = c.get(q_id)
            assert r.status_code == 200

        # Borremos el problema
        result = c.delete("/problema/{}".format(ultimo_problema_id))
        assert result.status_code == 204
        problemas = c.get("/problemas")
        assert problemas.status_code == 200
        assert len(problemas.json) == n_problemas_antes - 1

        # Verifiquemos que todas sus cuestiones han sido borradas
        for q_id in ultimas_cuestiones_ids:
            r = c.get(q_id, expect_errors=True)
            assert r.status_code == 404

        # Verifiquemos que han desaparecido los tags nuevos, pero que
        # siguen los viejos
        tags = c.get("/tags").json
        assert "ftp" not in tags
        assert "sftp" not in tags
        assert "sd" in tags

    def test_delete_undeletable(self):
        """Intentamos borrar un problema que no debería poder ser borrado"""
        # Tomamos una pregunta del examen 2, que está cerrado
        result = self.c.get("/examen/2")
        assert result.status_code == 200
        assert result.json["estado"] == "cerrado"

        problema = result.json["problemas"][0]
        result = self.c.delete("/problema/{}".format(problema["id"]), expect_errors=True)
        assert result.status_code == 422
        assert "no puede borrarse por aparecer en exámenes cerrados" in result.json["debug"]

    def test_post_problema_minimalista(self):
        c = self.c

        # Estos son los contenidos mínimos exigidos para crear un problema
        # Al menos una cuestión, al menos un tag (no vacío), obligatorio
        # el enunciado, el resumen y un creador cuyo email figure en
        # la base de datos
        #
        # La cuestíón debe contener como mínimo enunciado y respuesta
        # Por defecto se le da puntos=1.0 si no especifica otro
        # La cuestión no necesita campo 'posicion', el servidor se lo
        # asigna según el orden que ocupa en la lista de cuestiones
        result = c.post_json("/problemas", {
            'cuestiones': [{'enunciado': 'foo', 'respuesta': 'bar'}],
            #'creador': {'email': 'jldiaz@uniovi.es'},
            'enunciado': 'Enunciado de prueba',
            'resumen': "Resumen",
            'tags': ["foo"]
        })
        assert result.status_code == 201
        assert result.json["creador"]["nombre"] == "Administrador"

    def test_post_problema_nuevo_errores_varios(self):
        """Probar a crear un problema nuevo enviando mal los parámetros"""
        c = self.c

        # Faltan todos los campos
        result = c.post_json("/problemas", {}, expect_errors=True)
        assert result.status_code == 422

        # Falta resumen, el resto bien
        result = c.post_json("/problemas", {
            'cuestiones': [{'enunciado': 'foo', 'respuesta': 'bar'}],
            'creador': {'email': 'jldiaz@uniovi.es'},
            'enunciado': 'Enunciado de prueba',
            'tags': [""]
        }, expect_errors=True)
        assert result.status_code == 422
        assert b"resumen" in result.body

        # Falta creador, resto bien
        result = c.post_json("/problemas", {
            'cuestiones': [{'enunciado': 'foo', 'respuesta': 'bar'}],
            'enunciado': 'Enunciado de prueba',
            'tags': ["foo"],
            'resumen': "Resumen"
        }, expect_errors=True)
        # NOTA: si falta el creador, wexam le pondrá uno, usando
        # el id que viene en el JWT. Y si se le pasaba un creador lo
        # sustituirá de todas formas por el que viene en el JWT
        assert result.status_code == 201
        assert result.json["creador"]["nombre"] == "Administrador"

        # Faltan cuestiones
        result = c.post_json("/problemas", {
            'creador': {'email': 'jldiaz@uniovi.es'},
            'enunciado': 'Enunciado de prueba',
            'tags': [""],
            'resumen': "Resumen"
        }, expect_errors=True)
        assert result.status_code == 422
        assert b"cuestiones" in result.body

        # La lista de cuestiones va vacía
        result = c.post_json("/problemas", {
            'cuestiones': [],
            'creador': {'email': 'jldiaz@uniovi.es'},
            'enunciado': 'Enunciado de prueba',
            'tags': [""],
            'resumen': "Resumen"
        }, expect_errors=True)
        assert result.status_code == 422
        assert b"cuestiones" in result.body

        # Una cuestión de la lista no tiene el formato correcto
        result = c.post_json("/problemas", {
            'cuestiones': [{}],
            'creador': {'email': 'jldiaz@uniovi.es'},
            'enunciado': 'Enunciado de prueba',
            'tags': [""],
            'resumen': "Resumen"
        }, expect_errors=True)
        assert result.status_code == 422
        assert b"Cuestion" in result.body

        # Faltan tags
        result = c.post_json("/problemas", {
            'cuestiones': [{'enunciado': 'foo', 'respuesta': 'bar'}],
            'creador': {'email': 'jldiaz@uniovi.es'},
            'enunciado': 'Enunciado de prueba',
            'resumen': "Resumen"
        }, expect_errors=True)
        assert result.status_code == 422
        assert b"tags" in result.body

        # La lista de tags va vacía
        result = c.post_json("/problemas", {
            'cuestiones': [{'enunciado': 'foo', 'respuesta': 'bar'}],
            'creador': {'email': 'jldiaz@uniovi.es'},
            'enunciado': 'Enunciado de prueba',
            'resumen': "Resumen",
            'tags': []
        }, expect_errors=True)
        assert result.status_code == 422
        assert b"tags" in result.body

        # Un tag es la cadena vacía
        result = c.post_json("/problemas", {
            'cuestiones': [{'enunciado': 'foo', 'respuesta': 'bar'}],
            'creador': {'email': 'jldiaz@uniovi.es'},
            'enunciado': 'Enunciado de prueba',
            'resumen': "Resumen",
            'tags': ["foo", "bar", ""]
        }, expect_errors=True)
        assert result.status_code == 422
        assert b"Tag.name" in result.body

    def test_put_problema_no_abierto(self):
        """Un problema no abierto no debe de poder cambiarse"""
        # El problema 1 pertenece al examen 2 que está cerrado, por tanto
        # no pueden hacerse cambios sobre él.
        # Tomamos una pregunta del examen 2, que está cerrado
        result = self.c.get("/examen/2")
        assert result.status_code == 200
        assert result.json["estado"] == "cerrado"

        problema = result.json["problemas"][0]
        result = self.c.put_json("/problema/{}".format(problema["id"]),
                        {'resumen': 'Nuevo resumen', 'enunciado': 'Nuevo enunciado'},
                        expect_errors=True)
        assert result.status_code == 422
        assert "El problema no puede modificarse por aparecer en exámenes cerrados" \
            in result.json["debug"]

    def test_put_problema_minimo(self):
        """Cambiar resumen o enunciado general de un problema"""
        c = self.c
        p1_antes = self.c.get('/problema/1')
        assert p1_antes.status_code == 200

        time.sleep(1)
        result = c.put_json('/problema/1', {'resumen': 'Nuevo resumen', 'enunciado': 'Nuevo enunciado'})
        assert result.status_code == 200

        p1_despues = self.c.get('/problema/1')
        assert p1_despues.status_code == 200

        assert p1_antes.json["resumen"] != p1_despues.json["resumen"]
        assert p1_antes.json["enunciado"] != p1_despues.json["enunciado"]

        assert self.son_iguales(p1_antes.json, p1_despues.json,
                                omitir=["resumen", "enunciado", "originalidad", "snippet"])

        # Comprobar timestamps
        p1_despues = self.c.get('/problema/1/full')
        assert p1_despues.status_code == 200
        verificar_timestamps(p1_despues.json["fecha_modificacion"],
                             p1_despues.json["fecha_creacion"])

    def test_put_problema_ignora_campos_desconocidos(self):
        """Si en el PUT van campos desconocidos, no tiene efecto"""
        c = self.c
        p1_antes = self.c.get('/problema/1/full')
        assert p1_antes.status_code == 200

        time.sleep(1)
        result = c.put_json('/problema/1', {'campo_desconocido': 'Valor arbitrario'})
        assert result.status_code == 200

        p1_despues = self.c.get('/problema/1/full')
        assert p1_despues.status_code == 200

        assert self.son_iguales(p1_antes.json, p1_despues.json)

        # Comprobar timestamps no han cambiado
        p1_despues.json["fecha_modificacion"] == p1_antes.json["fecha_modificacion"]

    def test_put_problema_dejar_cuestiones_igual(self):
        """Si la lista de cuestiones tiene los mismos ID que los que ya tenía, eso no
        se modificará"""
        c = self.c
        p1_antes = self.c.get('/problema/1/full')
        assert p1_antes.status_code == 200

        ids_cuestiones = [ {"id": q["id"] } for q in p1_antes.json["cuestiones"]]
        result = c.put_json('/problema/1', {'cuestiones': ids_cuestiones })
        assert result.status_code == 200

        p1_despues = self.c.get('/problema/1/full')
        assert p1_despues.status_code == 200

        assert self.son_iguales(p1_antes.json, p1_despues.json, omitir=["fecha_modificacion"])

    def test_put_problema_mal_id_cuestion(self):
        """En la lista de cuestiones pongo el id de una que no era de este problema"""
        c = self.c
        p1_antes = self.c.get('/problema/1/full')
        assert p1_antes.status_code == 200

        ids_cuestiones = [ {"id": q["id"] } for q in p1_antes.json["cuestiones"]]
        id_mal = str(ids_cuestiones[0]["id"]) + "123"
        ids_cuestiones[0]["id"] = id_mal
        result = c.put_json('/problema/1', {'cuestiones': ids_cuestiones }, expect_errors=True)
        assert result.status_code == 422
        id_mal = id_mal.split("/")[-1]
        assert ("id=%s" % id_mal) in result.json["debug"]

    def test_put_problema_mal_cuestiones(self):
        """En la lista de cuestiones no envío diccionarios"""
        c = self.c
        p1_antes = self.c.get('/problema/1/full')
        assert p1_antes.status_code == 200

        result = c.put_json('/problema/1', {'cuestiones': ["uno", "dos"] }, expect_errors=True)
        assert result.status_code == 422
        assert "Las cuestiones no están en el formato apropiado" in result.json["debug"]

        result = c.put_json('/problema/1', {'cuestiones': [{}, {}] }, expect_errors=True)
        assert result.status_code == 422
        assert "enunciado is required" in result.json["debug"]

    def test_put_problema_modificar_una_cuestion(self):
        """Modifico parte de una cuestión, gracias a su id"""
        c = self.c
        p1_antes = self.c.get('/problema/1/full')
        assert p1_antes.status_code == 200

        cuestiones = [ {"id": q["id"] } for q in p1_antes.json["cuestiones"]]
        q1_antes = dict(p1_antes.json["cuestiones"][0])

        # Compruebo que antes de mi modificación, no tiene explicación y vale 1 punto
        assert q1_antes["explicacion"] == ""
        assert q1_antes["puntos"] == 1

        # Ahora modifico su explicación y puntuación
        cuestiones[0].update(explicacion="Ahora tiene explicación", puntos=3)
        time.sleep(1)         # Dejo pasar un 1s para afectar al timestamp de modificación
        result = c.put_json('/problema/1', {'cuestiones': cuestiones })
        assert result.status_code == 200

        p1_despues = self.c.get('/problema/1/full')
        assert p1_despues.status_code == 200

        # El resto del problema sigue igual, salvo la puntuación total
        assert self.son_iguales(p1_antes.json, p1_despues.json,
                    omitir=["cuestiones", "puntos", "fecha_modificacion", "snippet"])
        assert p1_antes.json["puntos"] == p1_despues.json["puntos"] - 2

        # Comprobemos que de la cuestión editada sólo ha cambiado lo que he pedido
        q1_despues = dict(p1_despues.json["cuestiones"][0])
        assert q1_despues["explicacion"] == "Ahora tiene explicación"
        assert q1_despues["puntos"] == 3
        assert q1_despues["enunciado"] == q1_antes["enunciado"]
        assert q1_despues["respuesta"] == q1_antes["respuesta"]

        # El resto de cuestiones han de ser iguales
        assert len(p1_antes.json["cuestiones"]) == len(p1_despues.json["cuestiones"])
        for q_a, q_d in zip(p1_antes.json["cuestiones"][1:], p1_despues.json["cuestiones"][1:]):
            assert q_a == q_d

        # Pero ha cambiado el timestamp del problema
        verificar_timestamps(p1_despues.json["fecha_modificacion"],
                             p1_antes.json["fecha_modificacion"])

    def test_put_problema_eliminar_una_cuestion(self):
        """Elimino una de las cuestiones que formaba parte del problema"""
        c = self.c
        p1_antes = self.c.get('/problema/1/full')
        assert p1_antes.status_code == 200

        cuestiones = [ {"id": q["id"] } for q in p1_antes.json["cuestiones"]]
        cuestiones.pop(0)
        eliminada = p1_antes.json["cuestiones"][0]

        # Ahora modifico el problema
        time.sleep(1)         # Dejo pasar un 1s para afectar al timestamp de modificación
        result = c.put_json('/problema/1', {'cuestiones': cuestiones })
        assert result.status_code == 200

        p1_despues = self.c.get('/problema/1/full')
        assert p1_despues.status_code == 200

        # El resto del problema sigue igual, salvo la puntuación total y el número total de cuestiones
        assert self.son_iguales(p1_antes.json, p1_despues.json,
                                omitir=["cuestiones", "puntos", "n_cuestiones", "snippet",
                                        "fecha_modificacion"])
        assert p1_antes.json["puntos"] == p1_despues.json["puntos"] + eliminada["puntos"]
        assert p1_antes.json["n_cuestiones"] == p1_despues.json["n_cuestiones"] + 1

        # El número de cuestiones ha menguado
        assert len(p1_antes.json["cuestiones"]) == len(p1_despues.json["cuestiones"]) + 1

        # La cuestión borrada ya no está en la base de datos
        result = c.get("/cuestion/{}".format(eliminada["id"]), expect_errors=True)
        assert result.status_code == 404

        # El resto de cuestiones han de ser iguales
        assert len(p1_antes.json["cuestiones"][1:]) == len(p1_despues.json["cuestiones"])
        for q_a, q_d in zip(p1_antes.json["cuestiones"][1:], p1_despues.json["cuestiones"]):
            assert q_a == q_d
        # Pero ha cambiado el timestamp del problema
        verificar_timestamps(p1_despues.json["fecha_modificacion"],
                             p1_antes.json["fecha_modificacion"])

    def test_put_problema_crear_una_cuestion(self):
        """Añado una cuestión nueva a un problema"""
        c = self.c
        p1_antes = self.c.get('/problema/1/full')
        assert p1_antes.status_code == 200

        cuestiones = [ {"id": q["id"] } for q in p1_antes.json["cuestiones"]]
        # Hay que crear una cuestión sin ID para que sea añadida
        cuestiones.append({"enunciado": "Esta es una cuestión nueva",
                            "respuesta": "La respuesta no importa",
                            "explicacion": "Inexplicable",
                            "puntos": 2})

        # Ahora modifico el problema
        time.sleep(1)         # Dejo pasar un 1s para afectar al timestamp de modificación
        result = c.put_json('/problema/1', {'cuestiones': cuestiones })
        assert result.status_code == 200

        p1_despues = self.c.get('/problema/1/full')
        assert p1_despues.status_code == 200

        # El resto del problema sigue igual, salvo la puntuación total y el número total de cuestiones
        assert self.son_iguales(p1_antes.json, p1_despues.json,
                                omitir=["cuestiones", "puntos", "n_cuestiones", "snippet",
                                        "originalidad", "fecha_modificacion"])
        assert p1_antes.json["puntos"] == p1_despues.json["puntos"] - 2
        assert p1_antes.json["n_cuestiones"] == p1_despues.json["n_cuestiones"] - 1

        # El número de cuestiones ha aumentado
        assert len(p1_antes.json["cuestiones"]) == len(p1_despues.json["cuestiones"]) - 1

        # Tenemos una cuestión más en la base de datos
        result = c.get("/cuestion/{}".format(p1_despues.json["cuestiones"][-1]["id"]))
        assert result.status_code == 200
        # Cuyos datos son los que pusimos
        assert result.json["enunciado"] == "Esta es una cuestión nueva"
        assert result.json["respuesta"] == "La respuesta no importa"
        assert result.json["puntos"] == 2
        assert result.json["explicacion"] == "Inexplicable"

        # El resto de cuestiones han de ser iguales
        assert len(p1_antes.json["cuestiones"]) == len(p1_despues.json["cuestiones"][:-1])
        for q_a, q_d in zip(p1_antes.json["cuestiones"], p1_despues.json["cuestiones"][:-1]):
            assert q_a == q_d
        # Pero ha cambiado el timestamp del problema
        verificar_timestamps(p1_despues.json["fecha_modificacion"],
                             p1_antes.json["fecha_modificacion"])

    def test_put_problema_cambiar_tags_por_otros_existentes(self):
        """Edito un problema para modificar su lista de tags, pero los que uso ya estaban
        en la base de datos"""
        c = self.c
        p1_antes = self.c.get('/problema/1/full')
        assert p1_antes.status_code == 200

        tags_problema_antes = p1_antes.json["tags"]
        tags_totales_antes = self.c.get("/tags").json
        nuevos_tags = tags_totales_antes[-2:]

        full_tags_antes = self.c.get("/tags/full").json

        # Cambio los tags del problema por otros, de la lista de tags
        result = c.put_json("/problema/1", {"tags": nuevos_tags})
        assert result.status_code == 200

        p1_despues = self.c.get('/problema/1/full')
        assert p1_despues.status_code == 200
        tags_problema_despues = p1_despues.json["tags"]
        tags_totales_despues = self.c.get("/tags").json
        full_tags_despues = self.c.get("/tags/full").json

        assert tags_totales_antes == tags_totales_despues
        assert set(tags_problema_despues) == set(nuevos_tags)

        # La lista expandida de tags antes y despues debe coincidir,
        # excepto por el recuento de veces usado de cada tag, ya que
        # algunos se decrementarán y otros se incrementarán
        assert len(full_tags_antes) == len(full_tags_despues)
        for antes, despues in zip(full_tags_antes, full_tags_despues):
            assert antes["id"] == despues["id"]
            assert antes["name"] == despues["name"]
            assert abs(antes["usado"] - despues["usado"]) <=1

    def test_put_problema_cambiar_tags_por_otros_inexistentes(self):
        """Edito un problema para modificar su lista de tags, y pongo otros
        que no estaban en la base de datos"""

        p1_antes = self.c.get('/problema/1/full')
        assert p1_antes.status_code == 200

        tags_problema_antes = p1_antes.json["tags"]
        full_tags_antes = self.c.get("/tags/full").json

        # Cambio los tags del problema por otros nuevos
        result = self.c.put_json("/problema/1", {"tags": ["nuevo1", "nuevo2"]})
        assert result.status_code == 200

        p1_despues = self.c.get('/problema/1/full')
        assert p1_despues.status_code == 200
        tags_problema_despues = p1_despues.json["tags"]
        full_tags_despues = self.c.get("/tags/full").json

        # La lista expandida de tags antes y despues debe ser diferente
        # pues hemos añadido tags nuevos
        assert len(full_tags_antes) == len(full_tags_despues) - len(tags_problema_despues)

        # Excepto por los dos añadidos, los anteriores coincidirán
        for antes, despues in zip(full_tags_antes, full_tags_despues[:-2]):
            assert antes["id"] == despues["id"]
            assert antes["name"] == despues["name"]
            assert abs(antes["usado"] - despues["usado"]) <=1

        # Los nuevos tendrán un recuento de 1
        for tag in full_tags_despues[-2:]:
            assert tag["name"] in tags_problema_despues
            assert tag["usado"] == 1

    def test_put_problema_eliminar_tag(self):
        """Edito un problema y le quito un tag que tenía. Pero ese tag era usado sólo
        por ese problema, por lo que al final debería desaparecer de la base de datos"""

        p1_antes = self.c.get('/problema/1')
        assert p1_antes.status_code == 200

        tags_problema_antes = p1_antes.json["tags"]
        tags_antes = self.c.get("/tags").json

        assert "nuevo1" in tags_problema_antes
        assert "nuevo2" in tags_problema_antes
        assert "nuevo1" in tags_antes
        assert "nuevo2" in tags_antes

        # Cambio los tags del problema por otros que ya existían
        tags = tags_antes[:2]
        result = self.c.put_json("/problema/1", {"tags": tags})
        assert result.status_code == 200

        p1_despues = self.c.get('/problema/1')
        assert p1_despues.status_code == 200
        tags_problema_despues = p1_despues.json["tags"]
        tags_despues = self.c.get("/tags").json

        assert "nuevo1" not in tags_problema_despues
        assert "nuevo2" not in tags_problema_despues
        assert tags[0] in tags_problema_despues
        assert tags[1] in tags_problema_despues

        # Y también han desaparecido de la base de datos
        assert len(tags_despues) == len(tags_antes) - len(tags)
        assert "nuevo1" not in tags_despues
        assert "nuevo2" not in tags_despues

    def son_iguales(self, antes, despues, omitir=[]):
        antes = dict(antes)
        despues = dict(despues)
        for campo in omitir:
            if campo in antes:
                del antes[campo]
            if campo in despues:
                del despues[campo]
        assert set(antes["tags"]) == set(despues["tags"])
        del antes["tags"]
        del despues["tags"]
        assert antes == despues
        return True

    def test_problema_clone(self):
        """Tras clonar un problema, comprobar el nuevo autor y fecha"""
        result = self.c.post("/problema/1/clone")
        assert result.status_code == 201
        # El nuevo autor ha de ser Admin
        assert result.json["creador"]["nombre"] == "Administrador"

        # Comparemos el problema original con el nuevo
        original = self.c.get("/problema/1/full")
        nuevo = self.c.get("/problema/{}/full".format(result.json["id"]))
        assert nuevo.status_code == 200

        # La nueva descripción ha de terminar en asterisco
        assert nuevo.json["resumen"] == original.json["resumen"] + ".1"

        # La fecha de creación del problema ha de ser posterior a la del original
        assert nuevo.json["fecha_creacion"] > original.json["fecha_creacion"]
        assert nuevo.json["problema_origen"] == 1

        # Hay relación de parentesco entre ellos
        assert len(original.json["problemas_derivados"]) == 1
        assert original.json["problemas_derivados"][0] == nuevo.json["id"]

        # La lista de tags ha de ser idéntica
        assert set(nuevo.json["tags"]) == set(original.json["tags"])

    def test_problema_clone_modificar_cuestiones(self):
        """Si modifico cuestiones del clonado, el original no cambia"""
        result = self.c.post("/problema/2/clone")
        assert result.status_code == 201

        id_nuevo = result.json["id"]

        nuevo = self.c.get("/problema/{}/full".format(id_nuevo))
        assert nuevo.status_code == 200
        cuestiones = [ {"id": q["id"] } for q in nuevo.json["cuestiones"]]

        # Cambio el enunciado y puntuación de la primera cuestión
        cuestiones[0].update(enunciado="Enunciado modificado", puntos=3)
        nuevo = self.c.put_json("/problema/{}".format(id_nuevo),
                                {'cuestiones': cuestiones })
        assert nuevo.status_code == 200

        nuevo = self.c.get("/problema/{}/full".format(id_nuevo))
        assert nuevo.status_code == 200

        original = self.c.get("/problema/2/full")
        assert original.status_code == 200

        # Verifico que ha cambiado la cuestión en el clonado
        enunciado = nuevo.json["cuestiones"][0]["enunciado"]
        assert enunciado == "Enunciado modificado"

        # Pero que no ha cambiado en el original
        enunciado = original.json["cuestiones"][0]["enunciado"]
        assert enunciado != "Enunciado modificado"


    def test_problemas_publicados(self):
        """Tras publicar un examen se reporta correctamente como 'publicado'
        cada uno de sus problemas"""

        # Publicamos examen 1
        result = self.c.put_json("/examen/1/", { "estado": "publicado" })
        assert result.status_code == 200

        result = self.c.get("/examen/1/full")
        assert result.status_code == 200
        assert result.json["estado"] == "publicado"
        assert result.json["fecha_modificacion"].startswith(result.json["publicado"])

        # Obtenemos su lista de problemas
        result = self.c.get("/examen/1/id_problemas")
        assert result.status_code == 200
        problemas_publicados = result.json

        # Verificamos que en la lista general todos salen como publicados
        result = self.c.get("/problemas")
        assert result.status_code == 200
        for problema in result.json:
            if problema["id"] in problemas_publicados:
                assert problema["publicado"] == True
            else:
                assert problema["publicado"] == False

class TestCirculoDesdeAdmin(TestWithMockDatabaseLoggedAsAdmin):
    """Comprueba operaciones sobre la entidad Circulo"""
    def test_get_lista_circulos(self):
        result = self.c.get("/circulos")
        assert result.status_code == 200
        assert len(result.json) == 2

    def test_get_detalles_circulo(self):
        result = self.c.get("/circulo/1")
        assert result.status_code == 200
        assert result.json["creador"]["nombre"] == "Jose Luis Díaz"
        assert result.json["nombre"] == "Sist. Dist."
        assert len(result.json["miembros"]) == 2
        miembros = set(m["nombre"] for m in result.json["miembros"])
        assert miembros == set(["Marco Antonio García",  "Joaquín Entrialgo"])

    def test_post_circulo_profesores_añadir_existente(self):
        """Añadir un profesor a un cículo en el que ya estaba, debe fallar"""
        # Intentamos añadir un profesor que ya estaba al círculo 1
        result = self.c.post_json("/circulo/1/miembros",
                                  {"miembros": [{"id": "2"}] },
                                  expect_errors=True)
        assert result.status_code == 422
        assert "No hay profesores que añadir" in result.json["debug"]

    def test_post_circulo_profesores_mal(self):
        """Añadir a un profesor inexistente a un círculo debe fallar"""
        result = self.c.post_json("/circulo/1/miembros",
                                  {"miembros": [{"id": "100"}] },
                                  expect_errors=True)
        assert result.status_code == 404
        # assert "ObjectNotFound" in result.json["debug"]

    def test_post_circulo_profesores(self):
        """Añadir profesores a un círculo"""
        # El circulo 1 tiene de profesor a marco (id=2) y nadie más
        # Voy a añadir una lista de dos profesores, uno de los cuales ya estaba
        result = self.c.post_json("/circulo/1/miembros",
                                  {"miembros": [{"id": "1"}, {"id": "2"}] })
        assert result.status_code == 200
        # Solo se habrá añadido el de id=1, pues el de id=2 e id=3 ya estaba
        assert len(result.json["miembros"]) == 3
        ids_miembros = [p["id"] for p in result.json["miembros"]]
        assert set((1,2,3)).issubset(ids_miembros)

        # Verifiquemos que ambos profesores figuran en el circulo en la base de datos
        with db_session:
            c1 = Circulo[1]
            for profe in [Profesor[1], Profesor[2]]:
                assert c1 in profe.circulos_en_que_esta
                assert profe in c1.miembros

    def test_delete_circulo_profesores(self):
        """Eliminar un profesor de un círculo"""
        # Tras el test anterior, el profesor 1 está en el círculo 1. Quitémosle
        result = self.c.delete_json("/circulo/1/miembros",
                                    {"miembros": [{"id": "1"}]})
        assert result.status_code == 200
        # Solo quedará un profesor
        assert len(result.json["miembros"]) == 2
        ids_miembros = [p["id"] for p in result.json["miembros"]]
        assert 2 in ids_miembros
        assert 3 in ids_miembros
        assert 1 not in ids_miembros

        # Verifiquemos en la base de datos
        with db_session:
            c1 = Circulo[1]
            assert c1 not in Profesor[1].circulos_en_que_esta
            assert c1 in Profesor[2].circulos_en_que_esta

    def test_delete_circulo_profesores_no_estaba(self):
        """Intentar eliminar a un profesor de un círculo en que no estaba es un error 422"""
        # Tras el test anterior el profesor 1 ya no está en el círculo, por lo que no puede quitarse
        result = self.c.delete_json("/circulo/1/miembros",
                                    {"miembros": [{"id": "1"}]},
                                    expect_errors=True)
        assert result.status_code == 422
        assert "No hay profesores que quitar" in result.json["debug"]

    def test_delete_circulo_profesores_mal(self):
        """Intentar eliminar un profesor inexistente de un círculo es un error 404"""
        result = self.c.delete_json("/circulo/1/miembros",
                                    {"miembros": [{"id": "100"}]},
                                    expect_errors=True)
        assert result.status_code == 404
        # assert "ObjectNotFound" in result.json["debug"]

    def test_post_circulo_problemas_añadir_existente(self):
        """Añadir un problema a un cículo en el que ya estaba, debe fallar"""
        # Intentamos añadir un profesor que ya estaba al círculo 1
        result = self.c.post_json("/circulo/1/problemas",
                                  {"problemas": [{"id": "1"}] },
                                  expect_errors=True)
        assert result.status_code == 422
        assert "No hay problemas que añadir" in result.json["debug"]

    def test_post_circulo_problemas_mal(self):
        """Añadir un problema inexistente a un círculo debe fallar"""
        result = self.c.post_json("/circulo/1/problemas",
                                  {"problemas": [{"id": "100"}] },
                                  expect_errors=True)
        assert result.status_code == 422
        assert "No hay problemas que añadir" in result.json["debug"]

    def test_post_circulo_problemas(self):
        """Añadir problemas a un círculo"""
        # El circulo 1 tiene los problemas 1, 2, 3
        # Voy a añadir una lista de dos problemas, uno de los cuales ya estaba
        result = self.c.post_json("/circulo/1/problemas",
                                  {"problemas": [{"id": "1"}, {"id": "5"}] })
        assert result.status_code == 200
        # Solo se habrá añadido el de id=5, pues el de id=1
        assert len(result.json["problemas"]) == 4
        ids_problemas = [p["id"] for p in result.json["problemas"]]
        assert set(ids_problemas) == set([1, 2, 3, 5])

        # Verifiquemos que ambos problemas figuran compartidos con ese circulo en la base de datos
        with db_session:
            c1 = Circulo[1]
            for problema in [Problema[1], Problema[5]]:
                assert c1 in problema.compartido_con
                assert problema in c1.problemas_visibles

    def test_delete_circulo_problemas(self):
        """Eliminar un problema de un círculo"""
        # Tras el test anterior, el problema 5 está en el círculo 1. Quitémosle
        result = self.c.delete_json("/circulo/1/problemas",
                                    {"problemas": [{"id": "5"}]})
        assert result.status_code == 200
        # Solo quedarán 3 problemsa
        assert len(result.json["problemas"]) == 3
        ids_problemas = [p["id"] for p in result.json["problemas"]]
        assert set(ids_problemas) == set([1, 2, 3])

        # Verifiquemos en la base de datos
        with db_session:
            c1 = Circulo[1]
            assert c1 not in Problema[5].compartido_con
            assert Problema[5] not in c1.problemas_visibles

    def test_delete_circulo_problemas_no_estaba(self):
        """Intentar eliminar a un problema de un círculo en que no estaba es un error 422"""
        # Tras el test anterior el problema 5 ya no está en el círculo, por lo que no puede quitarse
        result = self.c.delete_json("/circulo/1/problemas",
                                    {"problemas": [{"id": "5"}]},
                                    expect_errors=True)
        assert result.status_code == 422
        assert "No hay problemas que quitar" in result.json["debug"]

    def test_delete_circulo_problemas_mal(self):
        """Intentar eliminar un problema inexistente de un círculo es un error 422"""
        result = self.c.delete_json("/circulo/1/problemas",
                                    {"problemas": [{"id": "100"}]},
                                    expect_errors=True)
        assert result.status_code == 422
        assert "No hay problemas que quitar" in result.json["debug"]

    def test_post_circulo(self):
        """Creación de un nuevo círculo"""
        result = self.c.get("/circulos")
        assert result.status_code == 200
        assert len(result.json) == 2

        result = self.c.post_json("/circulos", { "nombre": "Círculo nuevo"})
        assert result.status_code == 201
        nuevo_id = result.json["id"]

        # Comprobar que hay uno más
        result = self.c.get("/circulos")
        assert result.status_code == 200
        assert len(result.json) == 3

        # Que es legible y sus atributos están bien
        result = self.c.get("/circulo/{}/full".format(nuevo_id))
        assert result.status_code == 200
        assert result.json["nombre"] == "Círculo nuevo"
        assert result.json["creador"]["nombre"] == "Administrador"
        assert len(result.json["miembros"]) == 0
        assert result.json["fecha_creacion"] == result.json["fecha_modificacion"]

    def test_delete_circulo(self):
        """Borrar un círculo lo elimina y actualiza correctamente a los profesores que estaban en él"""
        result = self.c.get("/circulos")
        assert result.status_code == 200
        assert len(result.json) == 3

        # Comenzamos por meter en el círculo recién creado a algún profesor más
        id_circulo = max( c["id"] for c in result.json)
        result = self.c.post_json("/circulo/{}/miembros".format(id_circulo),
                                 {"miembros": [{"id": "1"}, {"id": "2"}]})
        assert result.status_code == 200
        assert len(result.json["miembros"]) == 2

        # Verifiquemos que los profes 1 y 2 están en este nuevo círculo
        circulos_en_que_estaba_profe = []
        with db_session:
            c = Circulo[id_circulo]
            for profe in [Profesor[1], Profesor[2]]:
                assert c in profe.circulos_en_que_esta
                assert profe in c.miembros
                circulos_en_que_estaba_profe.append(len(profe.circulos_en_que_esta))


        # Ahora borramos el círculo
        result = self.c.delete("/circulo/{}".format(id_circulo))
        assert result.status_code == 204

        # Verifiquemos en la base de datos los cambios
        with db_session:
            assert len(Circulo.select()) == 2
            assert (circulos_en_que_estaba_profe[0] ==
                    len(Profesor[1].circulos_en_que_esta) + 1)
            assert (circulos_en_que_estaba_profe[1] ==
                    len(Profesor[2].circulos_en_que_esta) + 1)


class TestPermisosUnlogged(TestWithMockDatabaseUnlogged):
    """Comprueba que se impide el acceso a todas las rutas si no se está logueado"""
    rutas_colecciones = [
            "/",
            "/tags",
            "/profesores",
            "/problemas",
            "/examenes",
            "/circulos",
            "/tags/full",
            "/profesores/full",
            "/problemas/full",
            "/problemas/mios",
            "/examenes/full",
            "/circulos/full",
        ]

    rutas_entidades = [
            '/profesor/{id}',
            '/problema/{id}',
            '/cuestion/{id}',
            '/examen/{id}',
            '/asignatura/{id}',
            '/tag/{id}',
            '/circulo/{id}',
            '/profesor/{id}/min',
            '/problema/{id}/min',
            '/problema/{id}/meta',
            '/problema/{id}/full',
            '/examen/{id}/min',
            '/examen/{id}/full',
            '/tag/{id}/min',
            '/tag/{id}/full',
            '/circulo/{id}/min',
            '/circulo/{id}/full',
        ]

    def verificar_acceso_prohibido(self, rutas):
        for ruta in rutas:
            resp = self.c.get(ruta, expect_errors=True)
        assert resp.status_code == 403

    def verificar_post_prohibido(self, rutas):
        for ruta in rutas:
            resp = self.c.post(ruta, expect_errors=True)
        assert resp.status_code == 403 or resp.status_code == 405

    def verificar_put_prohibido(self, rutas):
        for ruta in rutas:
            resp = self.c.put(ruta, expect_errors=True)
        assert resp.status_code == 403 or resp.status_code == 405

    def verificar_delete_prohibido(self, rutas):
        for ruta in rutas:
            resp = self.c.delete(ruta, expect_errors=True)
        assert resp.status_code in [403, 404, 405]

    def test_get_forbidden_for_all_collections(self):
        "Se impide el acceso a todas las rutas de colecciones"
        rutas = self.rutas_colecciones
        self.verificar_acceso_prohibido(rutas)

    def test_get_forbidden_for_all_entities(self):
        "Se impide el acceso a todas las rutas de entidades"
        rutas = [ruta.format(id=1) for ruta in self.rutas_entidades]
        self.verificar_acceso_prohibido(rutas)

    def test_post_forbidden_for_all_collections(self):
        "Se impide crear elementos en cualquier colección"
        rutas = self.rutas_colecciones
        self.verificar_post_prohibido(rutas)

    def test_put_forbidden_for_all_entitites(self):
        "Se impide modificar cualquier elemento"
        rutas = [ruta.format(id=1) for ruta in self.rutas_entidades]
        self.verificar_put_prohibido(rutas)

    def test_delete_forbidden_for_all_entitites(self):
        "Se impide modificar cualquier elemento"
        rutas = [ruta.format(id=1) for ruta in self.rutas_entidades]
        self.verificar_delete_prohibido(rutas)


class TestPermisosGetParaProfesor(TestWithMockDatabaseLoggedAsProfesor):
    """Comprueba que un profesor sólo puede acceder a ciertas cosas"""

    def test_get_tags(self):
        """El profesor puede ver la lista de tags completa"""
        result = self.get_as("/tags", user="marco")
        assert result.status_code == 200
        assert len(result.json) == 4
        result = self.get_as("/tags", user="javier")
        assert result.status_code == 200
        assert len(result.json) == 4

    def test_get_tag(self):
        """El profesor puede ver un tag particular, todas sus vistas"""
        result = self.get_as("/tag/1", user="marco")
        assert result.status_code == 200
        result = self.get_as("/tag/1/min", user="marco")
        assert result.status_code == 200
        result = self.get_as("/tag/1/full", user="marco")
        assert result.status_code == 200

    def test_get_profesores(self):
        """El profesor puede ver la lista de profesores"""
        result = self.get_as("/profesores", user="jldiaz")
        assert result.status_code == 200
        assert len(result.json) == 5   # Ven sólo 5, el admin no es visible
        result = self.get_as("/profesores", user="marco")
        assert result.status_code == 200
        assert len(result.json) == 5   # Ven sólo 5, el admin no es visible

    def test_get_profesor(self):
        """El profesor puede ver detalles sólo de sí mismo"""
        for id_, prof in enumerate(("jldiaz", "marco", "joaquin",
                                    "arias", "javier")):
            result = self.get_as(
                "/profesor/{}".format(id_+1),
                user=prof)
            assert result.status_code == 200
            assert prof in result.json["email"]
            assert result.json["id"] == id_+1
            # Pero no puede ver detalles de otro
            result = self.get_as(
                "/profesor/{}".format(id_+2),
                user=prof, expect_errors=True)
            assert result.status_code == 403

    def test_get_circulos(self):
        """El profesor sólo puede ver los círculos que él mismo ha creado"""
        # Este usuario ha creado dos circulos
        result = self.get_as("/circulos", user="jldiaz")
        assert result.status_code == 200
        assert len(result.json) == 2

        # Pero este no ha creado ninguno
        result = self.get_as("/circulos", user="arias")
        assert result.status_code == 200
        assert len(result.json) == 0

        # Lo mismo si intentan ver la versión full
        result = self.get_as("/circulos/full", user="jldiaz")
        assert result.status_code == 200
        assert len(result.json) == 2
        # Verifiquemos que el creador es el usuario 1
        for circulo in result.json:
            assert circulo["creador"]["id"] == 1

        result = self.get_as("/circulos/full", user="arias")
        assert result.status_code == 200
        assert len(result.json) == 0

    def test_get_circulo(self):
        """El profesor puede ver los detalles de un círculo si es su creador"""
        # jldiaz ha creado los círculos 1 y 2
        for circulo in (1,2):
            result = self.get_as("/circulo/{}".format(circulo), user="jldiaz")
            assert result.status_code == 200
            assert result.json["creador"]["id"] == 1
            result = self.get_as("/circulo/{}/min".format(circulo), user="jldiaz")
            assert result.status_code == 200
            result = self.get_as("/circulo/{}/full".format(circulo), user="jldiaz")
            assert result.status_code == 200

        # Marco no ha creado ninguno de ellos, se le ha de prohibir el acceso
        for circulo in (1,2):
            result = self.get_as(
                "/circulo/{}".format(circulo), user="marco",
                expect_errors=True)
            assert result.status_code == 403
            result = self.get_as(
                "/circulo/{}/min".format(circulo), user="marco",
                expect_errors=True)
            assert result.status_code == 403
            result = self.get_as(
                "/circulo/{}/full".format(circulo), user="marco",
                expect_errors=True)
            assert result.status_code == 403

    def test_get_examenes(self):
        """El profesor sólo puede ver los exámenes que él mismo ha creado"""
        result = self.get_as("/examenes", user="jldiaz")
        assert result.status_code == 200
        assert len(result.json) == 0

        result = self.get_as("/examenes", user="javier")
        assert result.status_code == 200
        assert len(result.json) == 1
        for examen in result.json:
            assert examen["creador"]["id"] == 5

    def test_get_examen(self):
        """El profesor puede ver los detalles de un examen si es su creador"""
        # javier ha creado el examen 5, puede verlo
        result = self.get_as("/examen/1", user="javier")
        assert result.status_code == 200
        assert result.json["creador"]["id"] == 5
        result = self.get_as("/examen/1/min", user="javier")
        assert result.status_code == 200
        result = self.get_as("/examen/1/full", user="javier")
        assert result.status_code == 200

        # jldiaz no es el creador
        for view in ("", "/min", "/full"):
            result = self.get_as("/examen/1{}".format(view),
                                 user="jldiaz",
                                 expect_errors=True)
            assert result.status_code == 403

    def test_get_problemas(self):
        """El profesor sólo puede ver los problemas que él mismo ha creado,
        más los que otros hayan compartido con él"""

        # Por ejemplo, todos los problemas de jldiaz fueron creados por él
        result = self.get_as("/problemas", user="jldiaz")
        assert result.status_code == 200
        assert len(result.json) == 4

        for problema in result.json:
            assert problema["creador"]["id"] == 1

        # Los problemas 3, 2 y 1 fueron creados por jldiaz, y los ha compartido
        # con el círculo 1, en el cual están los profesores Marco (2) y Joaquin (3)

        # Marco puede ver los problemas compartidos
        result = self.get_as("/problemas", user="marco")
        assert result.status_code == 200

        ids = [p["id"] for p in result.json]
        assert set(ids) >= set([1, 2, 3])
        # Y los que no son compartidos, es que son suyos
        for problema in result.json:
            if problema["id"] not in [1, 2, 3]:
                assert problema["creador"]["id"] == 2

        # Lo mismo para joaquin, quien además está en el círculo 2
        # a través del cual recibe acceso al problema 4
        result = self.get_as("/problemas", user="joaquin")
        assert result.status_code == 200

        ids = [p["id"] for p in result.json]
        assert set(ids) >= set([1, 2, 3, 4])
        # Y los que no son compartidos, es que son suyos
        for problema in result.json:
            if problema["id"] not in [1, 2, 3, 4]:
                assert problema["creador"]["id"] == 3


class TestPermisosPutParaProfesor(TestWithMockDatabaseLoggedAsProfesor):
    """Comprueba que un profesor sólo puede modificar lo que le pertenece"""
    def test_put_profesor(self):
        # Javier no es el usuario 1, no puede cambiar sus datos
        result = self.put_as("/profesor/1", {"email": "micorreo@dot.com"},
                             user="javier",
                             expect_errors=True)
        assert result.status_code == 403
        # Pero sí es el usuario 5, sí puede cambiarlos
        result = self.put_as("/profesor/5", {"email": "micorreo@dot.com"},
                             user="javier",
                             expect_errors=False)
        assert result.status_code == 200
        assert result.json["email"] == "micorreo@dot.com"

        # Una vez modificado, el cambio es permanente
        result = self.get_as("/profesor/5", user="javier")
        assert result.status_code == 200
        assert result.json["email"] == "micorreo@dot.com"

    def test_put_problema(self):
        # Javier no es el autor del problema 1, no puede cambiarlo
        result = self.put_as("/problema/1", {"resumen": "Resumen cambiado"},
                             user="javier",
                             expect_errors=True)
        assert result.status_code == 403

        # Pero jldiaz sí
        result = self.put_as("/problema/1", {"resumen": "Resumen cambiado"},
                             user="jldiaz",
                             expect_errors=False)
        assert result.status_code == 200

        # Una vez modificado, el cambio es permanente
        result = self.get_as("/problema/1", user="jldiaz")
        assert result.status_code == 200
        assert result.json["resumen"] == "Resumen cambiado"

    def test_put_circulo(self):
        """Cambiar el nombre de un círculo"""
        # Javier no es el dueño del círculo 1, no puede cambiarlo
        result = self.put_as("/circulo/1", {"nombre": "Nuevo nombre"},
                             user="javier",
                             expect_errors=True)
        assert result.status_code == 403

        # Pero jldiaz sí
        result = self.put_as("/circulo/1", {"nombre": "Nuevo nombre"},
                             user="jldiaz",
                             expect_errors=False)
        assert result.status_code == 200

        # Una vez modificado, el cambio es permanente
        result = self.get_as("/circulo/1", user="jldiaz")
        assert result.status_code == 200
        assert result.json["nombre"] == "Nuevo nombre"


class TestPermisosPostParaProfesor(TestWithMockDatabaseLoggedAsProfesor):
    """Comprueba que un profesor sólo puede añadir recursos a ciertos lugares"""
    def test_post_profesor(self):
        # Nadie que no sea admin puede añadir profesores
        result = self.post_as("/profesores",
                            { "nombre": "A. Nónimo",
                              "email": "user@example.com",
                              "role": "profesor",
                              "password": "string"
                             },
                             user="javier",
                             expect_errors=True)
        assert result.status_code == 403

    def test_post_problema(self):
        # Cualquier usuario logueado puede crear problemas (no pun intended)
        result = self.post_as("/problemas",
                                {
                                    "cuestiones": [
                                        {
                                        "enunciado": "Enunciado de la cuestión",
                                        "respuesta": "Texto de la respuesta",
                                        "explicacion": "Explicación adicional opcional",
                                        "puntos": 2
                                        }
                                    ],
                                    "enunciado": "Enunciado general, antes de las cuestiones",
                                    "resumen": "Resumen de una línea del problema",
                                    "tags": [
                                        "sd",
                                        "ftp"
                                        ]
                                },
                                user="javier")
        assert result.status_code == 201

    def test_post_circulo(self):
        # Cualquier usuario logueado puede crear un círculo
        result = self.post_as("/circulos",
                              {
                                  "nombre": "Nombre del círculo"
                              },
                              user="marco")
        assert result.status_code == 201

    def test_post_circulo_profesores(self):
        # Añadir profesores a un círculo sólo puede hacerlo el propietario del círculo
        # Javier no es el propietario del círculo 1, no puede verlo:
        result = self.get_as("/circulo/1/miembros",
                                user="javier",
                                expect_errors=True)
        assert result.status_code == 403
        # Tampoco puede por tanto añadir profesores en él
        result = self.post_as("/circulo/1/miembros",
                              {"miembros": [ {"id": "5" }]},
                              user="javier",
                              expect_errors=True)
        assert result.status_code == 403

    def test_post_examen(self):
        # Cualquier usuario logueado puede crear exámenes
        datos = {
                    "id": "Esto será ignorado",
                    "creador": "Esto será ignorado",
                    "problemas": [ "Esto será ignorado" ],
                    "asignatura": "Fundamentos de Computadores",
                    "titulacion": "Informática",
                    "convocatoria": "Enero",
                    "estado": "abierto",
                    "fecha": "20180517",
                    "intro": "Blah, blah",
                    "tipo": "A"
                }
        result = self.post_as("/examenes", datos, user="marco")
        assert result.status_code == 201
        assert result.json["creador"]["nombre"] == "Marco Antonio García"

    def test_post_examen_clone(self):
        """Sólo quien puede ver un problema podrá clonarlo"""
        # Joaquín es propietario del problema 7, puede clonarlo
        result = self.post_as("/problema/7/clone", user="joaquin")
        assert result.status_code == 201
        assert result.json["creador"]["nombre"] == "Joaquín Entrialgo"

        # No es propietario del problema 1, pero lo puede ver, luego puede clonarlo
        result = self.post_as("/problema/1/clone", user="joaquin")
        assert result.status_code == 201
        assert result.json["creador"]["nombre"] == "Joaquín Entrialgo"

        # En cambio no es propietario del 5, ni puede verlo, luego la clonación dará error
        result = self.post_as("/problema/5/clone", user="joaquin", expect_errors=True)
        assert result.status_code == 403


class TestPermisosDeleteParaProfesor(TestWithMockDatabaseLoggedAsProfesor):
    """Comprueba que un profesor sólo puede borrar lo que le pertenece"""
    def test_delete_profesor(self):
        # Nadie que no sea admin puede borrar profesores
        result = self.delete_as("/profesor/1",
                             user="javier",
                             expect_errors=True)
        assert result.status_code == 403

    def test_delete_problema(self):
        # Javier no es el autor del problema 1, no puede borrarlo
        result = self.delete_as("/problema/1",
                             user="javier",
                             expect_errors=True)
        assert result.status_code == 403

        # Pero jldiaz sí
        result = self.delete_as("/problema/1",
                             user="jldiaz",
                             expect_errors=False)
        assert result.status_code == 204

    def test_delete_circulo_profesores(self):
        # Javier no es el creador del círculo 1, no puede verlo
        result = self.get_as("/circulo/1/miembros",
                                user="javier",
                                expect_errors=True)
        assert result.status_code == 403
        # Tampoco puede por tanto borrar profesores en él
        result = self.delete_as("/circulo/1/miembros",
                                {"miembros": [ {"id": "2" }]},
                                user="javier",
                                expect_errors=True)
        assert result.status_code == 403
        # Pero jldiaz sí
        result = self.delete_as("/circulo/1/miembros",
                                {"miembros": [ {"id": "2"} ]},
                                user="jldiaz",
                                expect_errors=False)
        assert result.status_code == 200

    def test_delete_circulo(self):
        # Javier no es el creador del círculo 1, no puede borrarlo
        result = self.delete_as("/circulo/1",
                                user="javier",
                                expect_errors=True)
        assert result.status_code == 403
        # Pero jldiaz sí
        result = self.delete_as("/circulo/1",
                                user="jldiaz",
                                expect_errors=False)
        assert result.status_code == 204

    def test_delete_examen(self):
        # jldiaz no es el creador del examen 1, no puede borrarlo
        result = self.delete_as("/examen/1",
                                user="jldiaz",
                                expect_errors=True)
        assert result.status_code == 403
        # Pero javier sí
        result = self.delete_as("/examen/1",
                                user="javier",
                                expect_errors=False)
        assert result.status_code == 204


class TestSubcollectionsParaAdmin(TestWithMockDatabaseLoggedAsAdmin):
    """Prueba a poner/quitar miembros y problemas en círculos y exámenes"""

    def test_añadir_problema_a_circulo(self):
        """Añade correctamente un problema que no estaba"""
        r = self.c.get("/circulo/1/id_problemas")
        assert r.status_code == 200
        assert 7 not in r.json

        r = self.c.post("/circulo/1/id_problemas?problema=7")
        assert r.status_code == 200

        r = self.c.get("/circulo/1/id_problemas")
        assert 7 in r.json

    def test_quitar_problema_de_circulo(self):
        """Quita correctamente un problema de un círculo"""
        r = self.c.get("/circulo/1/id_problemas")
        assert r.status_code == 200
        assert 7 in r.json

        r = self.c.delete("/circulo/1/id_problemas?problema=7")
        assert r.status_code == 200

        r = self.c.get("/circulo/1/id_problemas")
        assert 7 not in r.json

    def test_añadir_problema_que_ya_estaba_en_circulo(self):
        """Añadir un problema que ya estaba debe causar error"""
        r = self.c.get("/circulo/1/id_problemas")
        assert r.status_code == 200
        assert 1 in r.json
        antes = r.json

        r = self.c.post("/circulo/1/id_problemas?problema=1",
                        expect_errors=True)
        assert r.status_code == 422
        assert "El elemento de id=1 ya estaba en la lista de problemas"\
                in r.json["debug"]

        r = self.c.get("/circulo/1/id_problemas")
        despues = r.json
        assert set(antes) == set(despues)

    def test_quitar_problema_que_no_estaba_en_circulo(self):
        """Quitar un problema que no estaba debe causar error"""
        r = self.c.get("/circulo/1/id_problemas")
        assert r.status_code == 200
        assert 7 not in r.json
        antes = r.json

        r = self.c.delete("/circulo/1/id_problemas?problema=7",
                        expect_errors=True)
        assert r.status_code == 422
        assert "El elemento de id=7 no estaba en la lista de problemas"\
                in r.json["debug"]

        r = self.c.get("/circulo/1/id_problemas")
        despues = r.json
        assert set(antes) == set(despues)

    def test_añadir_miembro_a_circulo(self):
        """Añade correctamente un profesor que no estaba"""
        r = self.c.get("/circulo/1/id_miembros")
        assert r.status_code == 200
        assert 1 not in r.json

        r = self.c.post("/circulo/1/id_miembros?miembro=1")
        assert r.status_code == 200

        r = self.c.get("/circulo/1/id_miembros")
        assert 1 in r.json

    def test_quitar_miembro_de_circulo(self):
        """Quita correctamente un miembro de un círculo"""
        r = self.c.get("/circulo/1/id_miembros")
        assert r.status_code == 200
        assert 1 in r.json

        r = self.c.delete("/circulo/1/id_miembros?miembro=1")
        assert r.status_code == 200

        r = self.c.get("/circulo/1/id_miembros")
        assert 1 not in r.json

    def test_añadir_miembro_que_ya_estaba_en_circulo(self):
        """Añadir un miembro que ya estaba debe causar error"""
        r = self.c.get("/circulo/1/id_miembros")
        assert r.status_code == 200
        assert 2 in r.json
        antes = r.json

        r = self.c.post("/circulo/1/id_miembros?miembro=2",
                        expect_errors=True)
        assert r.status_code == 422
        assert "El elemento de id=2 ya estaba en la lista de miembros"\
                in r.json["debug"]

        r = self.c.get("/circulo/1/id_miembros")
        despues = r.json
        assert set(antes) == set(despues)

    def test_quitar_miembro_que_no_estaba_en_circulo(self):
        """Quitar un miembro que no estaba debe causar error"""
        r = self.c.get("/circulo/1/id_miembros")
        assert r.status_code == 200
        assert 1 not in r.json
        antes = r.json

        r = self.c.delete("/circulo/1/id_miembros?miembro=1",
                        expect_errors=True)
        assert r.status_code == 422
        assert "El elemento de id=1 no estaba en la lista de miembros"\
                in r.json["debug"]

        r = self.c.get("/circulo/1/id_miembros")
        despues = r.json
        assert set(antes) == set(despues)

    # Ahora poner y quitar problemas de examenes
    def test_añadir_problema_a_examen(self):
        """Añade correctamente un problema que no estaba"""
        r = self.c.get("/examen/1/id_problemas")
        assert r.status_code == 200
        assert 7 not in r.json
        antes = r.json

        r = self.c.post("/examen/1/id_problemas?problema=7")
        assert r.status_code == 200

        r = self.c.get("/examen/1/id_problemas")
        assert 7 in r.json

        # Verificar que ha sido añadido al final
        despues = r.json
        assert antes + [7] == despues

    def test_quitar_problema_de_examen(self):
        """Quita correctamente un problema de un examen"""
        r = self.c.get("/examen/1/id_problemas")
        assert r.status_code == 200
        assert 7 in r.json
        antes = r.json

        r = self.c.delete("/examen/1/id_problemas?problema=7")
        assert r.status_code == 200

        r = self.c.get("/examen/1/id_problemas")
        assert 7 not in r.json

        # Verificar que el orden de los demás no se ha alterado
        despues = r.json
        antes.remove(7)
        assert antes == despues

    def test_añadir_problema_que_ya_estaba_en_examen(self):
        """Añadir un problema que ya estaba debe causar error"""
        r = self.c.get("/examen/1/id_problemas")
        assert r.status_code == 200
        assert 2 in r.json
        antes = r.json

        r = self.c.post("/examen/1/id_problemas?problema=2",
                        expect_errors=True)
        assert r.status_code == 422
        assert "El elemento de id=2 ya estaba en la lista de problemas"\
                in r.json["debug"]

        r = self.c.get("/examen/1/id_problemas")
        despues = r.json
        assert antes == despues

    def test_quitar_problema_que_no_estaba_en_examen(self):
        """Quitar un problema que no estaba debe causar error"""
        r = self.c.get("/examen/1/id_problemas")
        assert r.status_code == 200
        assert 7 not in r.json
        antes = r.json

        r = self.c.delete("/examen/1/id_problemas?problema=7",
                        expect_errors=True)
        assert r.status_code == 422
        assert "El elemento de id=7 no estaba en la lista de problemas"\
                in r.json["debug"]

        r = self.c.get("/examen/1/id_problemas")
        despues = r.json
        assert antes == despues


class TestSubcollectionsParaProfesor(TestWithMockDatabaseLoggedAsProfesor):
    """Prueba a poner/quitar miembros y problemas en círculos y exámenes
    verificando que cumple las restricciones de acceso para un profesor"""

    def test_añadir_problema_no_visible_a_circulo(self):
        """Un problema no visible para el usuario no puede ser añadido
        a un círculo"""

        # jldiaz no puede ver el problema 7, por tanto no podrá añadirlo
        r = self.get_as("/circulo/1/id_problemas", user="jldiaz")
        assert r.status_code == 200
        assert 7 not in r.json

        r = self.post_as("/circulo/1/id_problemas?problema=7",
                            user="jldiaz", expect_errors=True)
        assert r.status_code == 422
        assert "No puedes compartir el problema 7 pues no eres propietario"\
               in r.json["debug"]

        r = self.get_as("/circulo/1/id_problemas", user="jldiaz")
        assert 7 not in r.json

    def test_añadir_problema_visible_pero_no_mio_a_circulo(self):
        """Un problema que el usuario no ha creado, no puede compartirlo
        aunque sea visible para él"""

        # marco puede ver el problema 1, pero no es su creador
        r = self.get_as("/problemas", user="marco")
        assert r.status_code == 200
        ids_problemas = [p["id"] for p in r.json]
        assert 1 in ids_problemas

        # Puede obtenerlo
        p1 = self.get_as("/problema/1", user="marco")
        assert p1.status_code == 200
        assert "Marco Antonio García" != p1.json["creador"]["nombre"]

        # Pero no puede añadirlo a un círculo. Vamos a comenzar por crear un círculo
        datos_circulo = { "nombre": "Circulo de prueba" }
        c = self.post_as("/circulos", datos_circulo, user="marco")
        assert c.status_code == 201
        c_id = c.json["id"]

        # E intentar añadir el problema
        r = self.post_as("/circulo/{}/id_problemas?problema=1".format(c_id),
                            user="marco", expect_errors=True)
        assert r.status_code == 422
        assert "No puedes compartir el problema 1 pues no eres propietario"\
               in r.json["debug"]

    def test_añadir_a_circulo_no_mio(self):
        """En un círculo no mío no puedo añadir ni leer nada"""

        r = self.get_as("/circulo/1/id_problemas", user="marco",
                       expect_errors=True)
        assert r.status_code == 403

        r = self.get_as("/circulo/1/id_miembros", user="marco",
                       expect_errors=True)
        assert r.status_code == 403

        r = self.post_as("/circulo/1/id_problemas?problema=7",
                            user="marco", expect_errors=True)
        assert r.status_code == 403

        r = self.post_as("/circulo/1/id_miembros?miembro=4",
                            user="marco", expect_errors=True)
        assert r.status_code == 403

    def test_añadir_y_quitar_a_circulo_mio_problema_mio(self):
        r = self.get_as("/circulo/2/id_problemas", user="jldiaz")
        assert r.status_code == 200
        assert 1 not in r.json

        r = self.post_as("/circulo/2/id_problemas?problema=1",
                            user="jldiaz")
        assert r.status_code == 200

        r = self.get_as("/circulo/2/id_problemas", user="jldiaz")
        assert 1 in r.json

        # También puedo quitarlo
        r = self.delete_as("/circulo/2/id_problemas?problema=1",
                            user="jldiaz")
        assert r.status_code == 200

        r = self.get_as("/circulo/2/id_problemas", user="jldiaz")
        assert 1 not in r.json

    def test_añadir_y_quitar_a_circulo_mio_problema_mio(self):
        r = self.get_as("/circulo/2/id_problemas", user="jldiaz")
        assert r.status_code == 200
        assert 1 not in r.json

        r = self.post_as("/circulo/2/id_problemas?problema=1",
                            user="jldiaz")
        assert r.status_code == 200

        r = self.get_as("/circulo/2/id_problemas", user="jldiaz")
        assert 1 in r.json

        # También puedo quitarlo
        r = self.delete_as("/circulo/2/id_problemas?problema=1",
                            user="jldiaz")
        assert r.status_code == 200

        r = self.get_as("/circulo/2/id_problemas", user="jldiaz")
        assert 1 not in r.json

    def test_añadir_y_quitar_a_circulo_mio_profesor(self):
        r = self.get_as("/circulo/2/id_miembros", user="jldiaz")
        assert r.status_code == 200
        assert 5 not in r.json

        r = self.post_as("/circulo/2/id_miembros?miembro=5",
                            user="jldiaz")
        assert r.status_code == 200

        r = self.get_as("/circulo/2/id_miembros", user="jldiaz")
        assert 5 in r.json

        # También puedo quitarlo
        r = self.delete_as("/circulo/2/id_miembros?miembro=5",
                            user="jldiaz")
        assert r.status_code == 200

        r = self.get_as("/circulo/2/id_miembros", user="jldiaz")
        assert 5 not in r.json

    def test_añadir_problema_no_mio_a_examen(self):
        """Un problema no visible para el usuario no puede añadirlo
        a un examen"""
        r = self.get_as("/examen/1/id_problemas", user="javier")
        assert r.status_code == 200
        assert 7 not in r.json

        # El problema 7 no es de javier, no puede añadirlo a su examen
        r = self.post_as("/examen/1/id_problemas?problema=7",
                            user="javier", expect_errors=True)
        assert r.status_code == 422
        assert "No puedes añadir el problema 7 pues no puedes verlo"\
                in r.json["debug"]

    def test_añadir_problema_a_examen_no_mio(self):
        r = self.get_as("/examen/1/id_problemas",
                        user="jldiaz", expect_errors=True)
        assert r.status_code == 403

        r = self.post_as("/examen/1/id_problemas?problema=7",
                            user="jldiaz", expect_errors=True)
        assert r.status_code == 403

    def test_añadir_y_quitar_a_examen_mio_problema_mio(self):
        r = self.get_as("/examen/1/id_problemas", user="javier")
        assert r.status_code == 200
        assert 10 not in r.json
        antes = r.json

        r = self.post_as("/examen/1/id_problemas?problema=10",
                            user="javier")
        assert r.status_code == 200

        r = self.get_as("/examen/1/id_problemas", user="javier")
        assert r.status_code == 200
        assert 10 in r.json
        despues = r.json
        assert despues == antes + [10]

        # Ahora lo borra
        r = self.delete_as("/examen/1/id_problemas?problema=10",
                            user="javier")
        assert r.status_code == 200

        r = self.get_as("/examen/1/id_problemas", user="javier")
        assert r.status_code == 200
        assert 10 not in r.json
        despues = r.json
        assert despues == antes

    def test_quitar_de_examen_mio_problema_no_mio(self):
        """Si el examen es mío, debe estar permitido quitar
        cualquier problema, incluso si no es mío"""
        r = self.get_as("/examen/1/id_problemas", user="javier")
        assert r.status_code == 200
        antes = r.json

        p8 = self.get_as("/problema/8", user="javier", expect_errors=True)
        assert p8.status_code == 403 # Este problema no es de javier
        assert 8 in antes           # Pero está en el examen

        # Voy a eliminarlo
        r = self.delete_as("/examen/1/id_problemas?problema=8",
                            user="javier")
        assert r.status_code == 200

        r = self.get_as("/examen/1/id_problemas", user="javier")
        assert r.status_code == 200
        assert 8 not in r.json
        despues = r.json
        antes.remove(8)
        assert despues == antes

        # Una vez eliminado ya no puedo añadirlo, porque no es mio
        r = self.post_as("/examen/1/id_problemas?problema=8",
                            user="javier", expect_errors=True)
        assert r.status_code == 422
        assert "No puedes añadir el problema 8 pues no puedes verlo"\
                in r.json["debug"]


class TestResetPassword(TestWithMockDatabaseUnlogged):
    """Comprueba que funciona el mecanismo de cambio de contraseña"""

    reset_url = ""

    def test_get_reset_password_with_unknonw_user_returns_404(self):
        """Si la ruta para cambiar contraseña corresponde a un usuario desconocido
        se produce un error 404"""
        result = self.c.get("/reset_password/desconocido@example.com",
                            expect_errors=True)
        assert result.status_code == 404


    # Normalmente un intento de acceder a la ruta /reset_password
    # implicaría un envío de un email al usuario. Para test y para evitar
    # que el email se envíe realmente, usamos "mocks"
    from unittest.mock import patch
    from wexam.appmodel import ResetPassword
    @patch.object(ResetPassword, "crear_mensaje",
                  wraps=ResetPassword.crear_mensaje)
    @patch.object(ResetPassword, "send_email")
    def test_get_reset_password_sends_email(self, mock_send, mock_crear):
        "La ruta para intentar cambiar clave existe y emite un correo"

        # Se accede a la ruta para solicitar cambio de contraseña
        self.c.get("/reset_password/jldiaz@uniovi.es")

        # Como consecuencia, la app deberá haber llamado a las funciones
        # para crear y enviar un email, lo que hemos capturado con los mock
        # Comprobemos que han sido llamadas
        assert mock_crear.called
        assert mock_send.called

        # Además, tenemos acceso a los parámetros que recibieron esas funciones
        send_msg_args = mock_send.call_args[1]
        crear_msg_args = mock_crear.call_args[1]

        # Por lo que podemos verificar que tienen los valores apropiados
        assert "Jose" == crear_msg_args["nombre"]
        assert "jldiaz%40uniovi.es" in  crear_msg_args["url_base"]
        assert "jldiaz@uniovi.es" == send_msg_args["toaddr"]
        assert "Hola Jose!" in send_msg_args["mensaje"]

        # Además podemos extraer le URL que ha sido "enviada" por email
        urls = [l for l in send_msg_args["mensaje"].split("\n") if l.startswith("http")]
        assert len(urls) == 1
        # Comprobar que coincide con el token correcto
        assert crear_msg_args["token"] in  urls[0]

        # Verifiquemos que ese token se refiere al email correcto
        claim = jwt.decode(crear_msg_args["token"], verify=False)
        assert claim["email"] == send_msg_args["toaddr"]

        # La guardamos para los restantes test (esto es una marranada,
        # he tenido que guardarla como atributo de clase porque según parece
        # cada vez que se ejecuta un método de una clase Test se instancia
        # esa clase, por lo que no puedo guardar estas cosas en un atributo
        # de objeto que sería lo más limpio)
        self.__class__.reset_url = urls[0]

    def test_get_submitted_url_returns_form(self):
        "Un get al url recibido devuelve un formulario"
        resp = self.c.get(self.__class__.reset_url)
        assert resp.status_code == 200
        assert "html" in resp.headers["Content-type"]

    def test_post_submitted_url_bad_parameters_are_detected(self):
        # Intentar un POST sin el token, debe dar error
        url_base, query = self.__class__.reset_url.split("?")
        resp = self.c.post_json(url_base, {"email": "jldiaz@uniovi.es",
                                           "password": "9876"},
                                expect_errors=True)
        assert resp.status_code == 422
        assert "Falta el token" in resp.json["debug"]

        # Intentar un POST con un token que no es ni JWT
        url = "{}?token=foobar".format(url_base)
        resp = self.c.post_json(url, {"email": "jldiaz@uniovi.es",
                                      "password": "9876"},
                                expect_errors=True)
        assert resp.status_code == 422
        assert "El token es inválido" in resp.json["debug"]

        # Intentar un POST con un token que sí es JWT,
        # pero la firma no es correcta
        token = jwt.encode({"email": "otro@uniovi.es"},
                           "secreto", "HS256")
        url = "{}?token={}".format(url_base, token)
        resp = self.c.post_json(url, {"email": "jldiaz@uniovi.es",
                                      "password": "9876"},
                                expect_errors=True)
        assert resp.status_code == 422
        assert "El token es inválido" in resp.json["debug"]

    @pytest.mark.skip
    def test_post_submitted_url_bad_user_is_detected(self):
        # Intentar un POST con el token correcto, pero poniendo otro usuario
        url = self.__class__.reset_url
        resp = self.c.post_json(url, {"email": "marco@uniovi.es",
                                      "password": "9876"},
                                expect_errors=True)
        assert resp.status_code == 422
        assert ("El token no es del email indicado en el JSON"
                in resp.json["debug"])

        # Cambiar el usuario que aparece en la ruta
        url_base, query = self.__class__.reset_url.split("?")
        url_base = url_base.replace("jldiaz%40uniovi.es", "marco%40uniovi.es")
        url = "{}?{}".format(url_base, query)
        resp = self.c.post_json(url, {"email": "jldiaz@uniovi.es",
                                      "password": "9876"},
                                expect_errors=True)
        assert resp.status_code == 422
        assert ("El token es inválido" in resp.json["debug"])

    def test_post_submitted_url_right_user_changes_password(self):
        url = self.__class__.reset_url
        resp = self.c.post_json(url, {"email": "jldiaz@uniovi.es",
                                      "password": "9876"})
        assert resp.status_code == 200
        assert "cambiada" in resp.body.decode()

        # Comprobemos si con la nueva clave puedo entrar
        respuesta = self.c.post_json('/login',
                                     {'email': 'jldiaz@uniovi.es',
                                      'password': '9876'},
                                     expect_errors=True)
        assert respuesta.status_code == 200
        assert "Authorization" in respuesta.headers
        auth_type, token = respuesta.headers["Authorization"].split()
        assert auth_type == "JWT"

    def test_post_submitted_url_cannot_be_reused(self):
        url = self.__class__.reset_url
        resp = self.c.post_json(url, {"email": "jldiaz@uniovi.es",
                                      "password": "9876"},
                                expect_errors=True)
        assert resp.status_code == 422
        assert "El token es inválido" in resp.json["debug"]


class TestCORSUnlogged(TestWithMockDatabaseUnlogged):
    """Comprobar las cabeceras CORS sin autorizaciones"""
    def test_cors_in_403(self):
        "Las respuestas 'prohibido' tienen cabecera CORS"
        respuesta = self.c.get('/', expect_errors=True)
        assert respuesta.status_code == 403
        assert 'Access-Control-Allow-Origin' in respuesta.headers

    def test_cors_in_404(self):
        "Las respuestas 'not found' tienen cabecera CORS"
        respuesta = self.c.get('/estonoexiste', expect_errors=True)
        assert respuesta.status_code == 404
        assert 'Access-Control-Allow-Origin' in respuesta.headers

    def test_cors_in_422(self):
        "Las respuestas 'datos no válidos' tienen cabecera CORS"
        respuesta = self.c.post_json('/login',
                                     {'foo': 'bar'},
                                     expect_errors=True)
        assert respuesta.status_code == 422
        assert 'Access-Control-Allow-Origin' in respuesta.headers


class TestCORSlogged(TestWithMockDatabaseLoggedAsProfesor):
    """Comprobar las cabeceras CORS con usuario autorizado"""
    def test_cors_in_preflight(self):
        "Ante un comando OPTIONS devuelve las cabeceras CORS apropiadas para permitirlo"
        respuesta = self.c.options('/problema/1')
        assert respuesta.status_code == 200
        assert 'Access-Control-Allow-Origin' in respuesta.headers
        assert 'Access-Control-Allow-Methods' in respuesta.headers
        assert 'Access-Control-Allow-Headers' in respuesta.headers
        assert 'authorization' in respuesta.headers.get('Access-Control-Allow-Headers')
        assert 'GET' in respuesta.headers.get('Access-Control-Allow-Methods')
        assert 'PUT' in respuesta.headers.get('Access-Control-Allow-Methods')
        assert 'POST' in respuesta.headers.get('Access-Control-Allow-Methods')
        assert 'DELETE' in respuesta.headers.get('Access-Control-Allow-Methods')

    def test_cors_in_GET(self):
        "Ante un GET válido la respuesta contiene las cabeceras CORS apropiadas"
        respuesta = self.get_as('/problema/1')
        assert respuesta.status_code == 200
        assert 'Access-Control-Allow-Origin' in respuesta.headers
        assert 'Access-Control-Allow-Methods' in respuesta.headers
        assert 'Access-Control-Allow-Headers' in respuesta.headers
        assert 'GET' in respuesta.headers.get('Access-Control-Allow-Methods')

    def test_cors_in_PUT(self):
        "Ante un PUT válido la respuesta contiene las cabeceras CORS apropiadas"
        respuesta = self.put_as('/profesor/1', {'email': 'jldiaz@gmail.com'}, user="jldiaz")
        assert respuesta.status_code == 200
        assert 'Access-Control-Allow-Origin' in respuesta.headers
        assert 'Access-Control-Allow-Methods' in respuesta.headers
        assert 'Access-Control-Allow-Headers' in respuesta.headers
        assert 'PUT' in respuesta.headers.get('Access-Control-Allow-Methods')

    def test_cors_in_POST(self):
        "Ante un POST válido la respuesta contiene las cabeceras CORS apropiadas"
        respuesta = self.put_as('/profesor/1', {'email': 'jldiaz@gmail.com'}, user="jldiaz")
        assert respuesta.status_code == 200
        assert 'Access-Control-Allow-Origin' in respuesta.headers
        assert 'Access-Control-Allow-Methods' in respuesta.headers
        assert 'Access-Control-Allow-Headers' in respuesta.headers
        assert 'POST' in respuesta.headers.get('Access-Control-Allow-Methods')

    def test_cors_in_DELETE(self):
        "Ante un DELETE válido la respuesta contiene las cabeceras CORS apropiadas"
        respuesta = self.delete_as('/problema/1', user="jldiaz")
        assert respuesta.status_code == 204
        assert 'Access-Control-Allow-Origin' in respuesta.headers
        assert 'Access-Control-Allow-Methods' in respuesta.headers
        assert 'Access-Control-Allow-Headers' in respuesta.headers
        assert 'DELETE' in respuesta.headers.get('Access-Control-Allow-Methods')
