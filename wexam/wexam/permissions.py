from more.jwtauth import JWTIdentityPolicy

from .app import App
from . import model
from . import db_collections as coll

# pylint: disable=too-few-public-methods

# ============ Clases para representar los permisos de la aplicación ====================
class EstarRegistrado:
    """Esta condición la tienen todos los usuarios registrados del sistema"""
    pass

class SerPropietario:
    """Esta condición la tiene un usuario sobre un objeto (problema, examen, ...)
    si es su creador, o sobre un usuario si es él mismo."""
    pass

class PoderVer:
    """Esta condición la tiene un usuario sobre un problema si es su creador o
    bien está en un círculo con el que el problema está compartido"""
    pass

class SerAdmin:
    """Esta condición sólo la cumplen los usuarios admin"""
    pass
# pylint: enable=too-few-public-methods



# =========== Funciones que verifican si se tiene o no cada permiso =====================
# pylint: disable=unused-argument
@App.identity_policy()
def get_identity_policy(settings):
    """Crea la política de identidad (usando jwt)"""
    jwtauth_settings = settings.jwtauth.__dict__.copy()
    return JWTIdentityPolicy(**jwtauth_settings)

@App.permission_rule(model=object, permission=EstarRegistrado)
def verificar_registrado(identity, que, permission):
    """Comprueba si el usuario puede ver el recurso, generico"""
    quien = model.Profesor.get(id=identity.id)
    # Si está en la base de datos, le permitimos ver el recurso
    if quien is not None:
        return True

@App.permission_rule(model=object, permission=SerAdmin)
def verificar_admin(identity, que, permission):
    """Comprueba si el usuario es admin"""
    quien = model.Profesor.get(id=identity.id)
    # Si está en la base de datos, comprobamos su rol
    return quien and quien.role == "admin"

@App.permission_rule(model=model.Profesor, permission=SerPropietario)
def verificar_propietario_usuario(identity, que, permission):
    """Comprueba si el usuario a que quiere acceder es él mismo."""

    quien = model.Profesor.get(id=identity.id)
    if quien and quien.role == "admin":
        return True
    return quien == que

@App.permission_rule(model=object, permission=SerPropietario)
def verificar_propietario(identity, que, permission):
    """Comprueba si el usuario es propietario del objeto"""

    quien = model.Profesor.get(id=identity.id)
    if quien and quien.role == "admin":
        return True
    if not hasattr(que, "creador"):
        return False
    return que.creador == quien

@App.permission_rule(model=coll.SubCollection, permission=SerPropietario)
def verificar_propietario_circulo(identity, que, permission):
    """Comprueba si el contenedor fue creada por el usuario."""

    quien = model.Profesor.get(id=identity.id)
    if quien and quien.role == "admin":
        return True
    return quien == que.contenedor.creador


@App.permission_rule(model=model.Cuestion, permission=SerPropietario)
def verificar_propietario_cuestion(identity, que, permission):
    """Comprueba si la cuestión fue creada por el usuario."""

    quien = model.Profesor.get(id=identity.id)
    if quien and quien.role == "admin":
        return True
    return quien == que.problema.creador

@App.permission_rule(model=model.Problema, permission=PoderVer)
def verificar_compartido_problema(identity, que, permission):
    """Comprueba si el usuario puede ver el problema"""
    if verificar_propietario(identity, que, permission):
        return True
    if not hasattr(que, "compartido_con"):
        return False
    quien = model.Profesor.get(id=identity.id)
    return quien in que.compartido_con.miembros

@App.permission_rule(model=model.Cuestion, permission=PoderVer)
def verificar_compartido_cuestion(identity, que, permission):
    """Comprueba si el usuario puede ver la cuestión"""
    # Lo que se reduce a mirar si puede ver el problema a que pertenece la cuestión
    return verificar_compartido_problema(identity, que.problema, permission)

@App.verify_identity()
def verify_identity(identity):
    """Indicar si confiamos en la identidad suministrada por el cliente"""
    # Cuando usamos JWT no es necesario verificar la identidad, pues viene
    # en un token firmado por nosotros mismos y en él confiamos
    return True

