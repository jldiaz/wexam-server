from datetime import datetime
from time import mktime, strptime
import yaml
from collections import OrderedDict

def my_date_decode(s):
    """Recibe una fecha en la forma ISO 8601 compacto ("20180514") y devuelve
    un objeto datetime"""
    return datetime.fromtimestamp(mktime(strptime(s, '%Y%m%d')))


def represent_ordereddict(dumper, data):
    value = []

    for item_key, item_value in data.items():
        node_key = dumper.represent_data(item_key)
        node_value = dumper.represent_data(item_value)

        value.append((node_key, node_value))

    return yaml.nodes.MappingNode(u'tag:yaml.org,2002:map', value)

yaml.add_representer(OrderedDict, represent_ordereddict)
