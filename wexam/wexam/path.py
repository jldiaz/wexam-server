"""Configura todas las rutas de la app y qué modelo va asociada a cada una"""
from .app import App
from . import model
from . import appmodel
from . import db_collections as coll


# Ruta raiz, actuará de "directorio" a las rutas de colecciones
@App.path(model=appmodel.Root, path='/')
def get_root():
    """/: Ruta raíz"""
    return appmodel.Root()


# Ruta para loguearse
@App.path(model=appmodel.Login, path='/login')
def get_login():
    """/login: Ruta para identificarse ante el sistema"""
    return appmodel.Login()

# Ruta para reiniciar base de datos
@App.path(model=appmodel.ResetDB, path="/reset_database")
def reset_database():
    """/reset_database: Ruta para restaurar la base de datos a la que se
    genera pseudo-aleatoriamente para testing"""
    return appmodel.ResetDB()

# Ruta para reiniciar contraseña
@App.path(model=appmodel.ResetPassword, path='/reset_password/{email}')
def get_reset_password(email):
    """/reset_password/{email}: Ruta para solicitar cambio de contraseña, y
    para realizarlo después a través de una de sus vistas"""
    quien = model.Profesor.get(email=email.lower())
    if not quien:
        return None
    return appmodel.ResetPassword(quien)

# Rutas a las tareas de conversión/compilación
@App.path(model=model.Tarea, path='/task/{id_}',
          variables=lambda obj: dict(id_=obj.id))
def get_tarea(id_):
    return model.Tarea.get(id=id_)

# ------------------ Rutas a colecciones ---------------------------
@App.path(model=coll.Tags, path='/tags')
def get_tags():
    """Obtener lista de tags"""
    return coll.Tags()


@App.path(model=coll.Profesores, path='/profesores/')
def get_profesores():
    """Obtener lista de profesores"""
    return coll.Profesores()


@App.path(model=coll.Problemas, path='/problemas')
def get_problemas(extra_parameters):
    """Obtener lista de problemas"""
    return coll.Problemas(extra_parameters)


@App.path(model=coll.Examenes, path="/examenes")
def get_examenes():
    """Obtener lista de exámenes"""
    return coll.Examenes()

@App.path(model=coll.Circulos, path="/circulos")
def get_circulos():
    """Obtener lista de círculos"""
    return coll.Circulos()

# ------------------ Rutas a entidades individuales ------------------
@App.path(model=model.Profesor, path='/profesor/{id_}',
          variables=lambda obj: dict(id_=obj.id))
def get_profesor(id_):
    """Acceso a un profesor por id"""
    return model.Profesor.get(id=id_)


@App.path(model=model.Problema, path='/problema/{id_}',
          variables=lambda obj: dict(id_=obj.id))
def get_problema(id_):
    """Acceso a un problerma por su id"""
    return model.Problema.get(id=id_)


@App.path(model=model.Cuestion, path='/cuestion/{id_}',
          variables=lambda obj: dict(id_=obj.id))
def get_cuestion(id_):
    """Acceso a una cuestión por su id"""
    return model.Cuestion.get(id=id_)


@App.path(model=model.Examen, path='/examen/{id_}',
          variables=lambda obj: dict(id_=obj.id))
def get_examen(id_):
    """Acceso a un examen por su id"""
    return model.Examen.get(id=id_)


@App.path(model=model.Asignatura, path='/asignatura/{id_}',
          variables=lambda obj: dict(id_=obj.id))
def get_asignatura(id_):
    """Acceso a una asignatura por su id"""
    return model.Asignatura.get(id=id_)


@App.path(model=model.Tag, path="/tag/{id_}",
          variables=lambda obj: dict(id_=obj.id))
def get_tag(id_):
    """"Acceso a un tag por su id"""
    return model.Tag.get(id=id_)


@App.path(model=model.Circulo, path="/circulo/{id_}",
          variables=lambda obj: dict(id_=obj.id))
def get_circulo(id_):
    """Acceso a un círculo por su id"""
    return model.Circulo.get(id=id_)


@App.path(model=coll.CirculoMiembros, path="/circulo/{id_}/id_miembros",
          variables=lambda obj: dict(id_=obj.id))
def get_circulo_miembros(id_, miembro=0, expanded=False):
    """Acceso a un círculo por su id, para manejar su lista de miembros"""
    circulo = model.Circulo.get(id=id_)
    if not circulo:
        return None
    return coll.CirculoMiembros(circulo, param=miembro, full=expanded)


@App.path(model=coll.CirculoProblemas, path="/circulo/{id_}/id_problemas",
          variables=lambda obj: dict(id_=obj.id))
def get_circulo_problemas(id_, problema=0, expanded=False):
    """Acceso a un círculo por su id, para manejar su lista de problemas"""
    circulo = model.Circulo.get(id=id_)
    if not circulo:
        return None
    return coll.CirculoProblemas(circulo, param=problema, full=expanded)

@App.path(model=coll.ExamenProblemas, path="/examen/{id_}/id_problemas",
          variables=lambda obj: dict(id_=obj.id))
def get_circulo_problemas(id_, problema=0, expanded=False):
    """Acceso a un examen por su id, para manejar su lista de problemas"""
    examen = model.Examen.get(id=id_)
    if not examen:
        return None
    return coll.ExamenProblemas(examen, param=problema, full=expanded)

# @App.path(model=coll.CirculoProblemas, path="/circulo/{id_}/problemas",
#           variables=lambda obj: dict(id_=obj.id))
# def get_circulo_problemas(id_, problemas):
#     """Acceso a un círculo por su id"""
#     return model.Circulo.get(id=id_)