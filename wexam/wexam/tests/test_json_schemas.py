"""Probar que el JSON que devuelven las diferentes rutas encajan
con lo especificado en el esquema"""

from test_app import (db, TestWithMockDatabaseLoggedAsAdmin)
from validator import Validator


class TestGetEntities(TestWithMockDatabaseLoggedAsAdmin):
    """Prueba la operación GET sobre diferentes entidades y
    verifica que el JSON que recibe como respuesta cumple con lo
    especificado en el esquema"""
    def setup_class(self):
        "Prepara base de datos, login y validador para los test"
        TestWithMockDatabaseLoggedAsAdmin.setup_class(self)
        self.validator = Validator()

    def get_valid_response(self, ruta, schema=None):
        """Efectúa un GET sobre la ruta y valida la respuesta frente al esquema"""
        resp = self.c.get(ruta)
        assert resp.status_code == 200
        data = resp.json
        if schema is None:
            schema = ruta[1:]
        self.validator.validate(schema, data)

    def test_all_collections(self):
        """Itera sobre todas las rutas que dan acceso a una colección
        y verifica que todas retornen JSON válido según el correspondiente
        esquema"""

        # El siguiente diccionario usa como claves las posibles
        # rutas para acceder a colecciones, y como valor la parte
        # del esquema contra el que deben ser validadas
        route_schemas = {
            "/tags": "tags",
            "/tags/full": "tags_full",
            "/profesores": "profesores",
            "/profesores/full": "profesores_full",
            "/problemas": "problemas",
            "/problemas/full": "problemas_full",
            "/examenes": "examenes",
            "/examenes/full": "examenes_full",
            "/circulos": "circulos",
            "/circulos/full": "circulos_full"
        }
        for route, schema in route_schemas.items():
            self.get_valid_response(route, schema)


    def test_all_entities(self):
        """Itera sobre todas las rutas que dan acceso a una entidad
        y sus versiones "min", normal y "full", y verifica que la respuesta
        en cada caso sea un JSON válido según el correspondiente esquema"""

        # El siguiente diccionario usa como claves las posibles
        # rutas para acceder a colecciones, y como valor la parte
        # del esquema contra el que deben ser validadas
        route_schemas = {
            "/tag/1": "tag",
            "/tag/1/min": "tag_min",
            "/tag/1/full": "tag_full",
            "/profesor/1": "user",
            "/profesor/1/min": "user_min",
            "/problema/1": "problema",
            "/problema/1/min": "problema_min",
            "/problema/1/full": "problema_full",
            "/cuestion/1": "cuestion",
            "/examen/1": "examen",
            "/examen/1/min": "examen_min",
            "/examen/1/full": "examen_full",
            "/asignatura/1": "asignatura",
            "/circulo/1": "circulo",
            "/circulo/1/min": "circulo_min",
            "/circulo/1/full": "circulo_full",
        }
        for route, schema in route_schemas.items():
            self.get_valid_response(route, schema)          