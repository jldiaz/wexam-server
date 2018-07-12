import sys
import os
from jsonschema import (Draft4Validator, validate)
import ruamel.yaml
yaml = ruamel.yaml.YAML(typ='safe')
yaml.safe_load = yaml.load


class Validator:
    def __init__(self):
        """Carga y verifica el esquema YAML"""
        path_to_schema = os.path.join(os.path.dirname(__file__), "wexam.schema.yaml")
        self.yaml_schema = yaml.safe_load(open(path_to_schema))
        Draft4Validator.check_schema(self.yaml_schema)

    def validate(self, entity, data):
        self.yaml_schema["$ref"] = "#/definitions/{}".format(entity)
        validate(data, self.yaml_schema)
