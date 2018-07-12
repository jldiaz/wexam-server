import os
import click
import requests
import getpass
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)





class Api:
    def __init__(self, url):
        self.url = url

    def help(self):
        print("Comandos disponibles:\n"
              "  help: muestra esta ayuda\n"
              "  users: muestra la lista de usuarios de la base de datos\n"
              "  adduser: permite añadir un usuario\n"
              "  deluser <id>: permite borrar un usuario\n"
              "  password <id>: premite cambiar la contraseña de un usuario\n"
              "  quit: termina la ejecución de este cliente"
        )




    def login(self, user, password):
        r = requests.post("{}/login".format(self.url), 
                          json={"email": user, "password": password}, 
                          verify=False)
        if r.status_code != 200:
            print(r.status_code, r.reason)
            print(r.content)
            print("Usuario admin o contraseña incorrectos")
            quit()
        self.token = r.json()

    def listusers(self):
        r = requests.get("{}/profesores".format(self.url), verify=False,
              headers={'Authorization': self.token})
        if r.status_code != 200:
            print("Error al obtener la lista de profesores")
            print(r.status_code, r.reason)
            print(r.json())
            return
        for p in r.json():
            self.print_profesor(p)

    def deluser(self, id_):
        print("CUIDADO!!! Al borrar el profesor se borrarán también todos los\n"
              "problemas, exámenes y círculos que el profesor haya creado.\n"
              "Para impedir el acceso al profesor es mejor cambiarle la contraseña.\n"
              "ESTAS SEGURO DE BORRARLE? (responde SÍ con mayúsculas y tilde)" )
        seguro = input("? ")
        if seguro != "SÍ":
            print("No se borra")
            return
        r = requests.delete("{}/profesor/{}".format(self.url, id_), verify=False,
              headers={'Authorization': self.token})
        if r.status_code != 204:
            print("Error al borrar al profesor")
            print(r.status_code, r.reason)
            print(r.json())
            return
        print("Profesor borrado")

    def change_password(self, id_):
        nueva = getpass.getpass("Nueva contraseña: ")
        repite = getpass.getpass("Repite contraseña: ")
        if nueva!=repite:
            print("Las contraseñas no coinciden")
            return
        r = requests.put("{}/profesor/{}".format(self.url, id_), verify=False,
              headers={'Authorization': self.token},
              json={"password": nueva})
        if r.status_code != 200:
            print("Error al cambiar la contraseña del profesor")
            print(r.status_code, r.reason)
            print(r.json())
            return
        print("Contraseña ok")


    def adduser(self):
        nombre = input("Nombre: ")
        email = input("Email: ")
        rol = input("Rol: ")
        r = requests.post("{}/profesores".format(self.url), verify=False,
              headers={'Authorization': self.token},
              json={"nombre": nombre, "email": email, "role": rol, "password": ""})
        if r.status_code != 201:
            print("Error al crear el profesor")
            print(r.status_code, r.reason)
            print(r.json())
            return
        id_ = r.json()["id"]
        self.change_password(id_)
        print("Profesor creado")

    def print_profesor(self, p):
        print('{}:  "{}" <{}> ({})'.format(p["id"], p["nombre"], p["email"], p["role"]))


@click.command()
@click.option("--url", default="https://atc156.edv.uniovi.es:8088/wexam-api", show_default=True,
              help="Url del backend al que se conectará")
@click.option("--user", default=None, 
              help="Usuario al que se subirán los problemas en el backend (si se omite se pedirá por consola)")
@click.option("--password", default=None,
              help="Contraseña del usuario (si se omite se pedirá por consola)")
def main(url, user, password):

    api = Api(url)

    if user is None:
        user = input("Usuario admin: ")
    if password is None:
        password = getpass.getpass("Contraseña: ")

    api.login(user, password)
    while True:
        cmd = input("Comando: ")
        if cmd == "adduser":
            api.adduser()
        elif cmd.startswith("deluser"):
            c = cmd.split()
            if len(c)<2:
                print("Debes especificar el id del profesor a borrar")
            else:
                id_ = int(c[1])
                api.deluser(id_)
        elif cmd == "users":
            api.listusers()
        elif cmd.startswith("password"):
            c = cmd.split()
            if len(c)<2:
                print("Debes especificar el id del profesor cuya contraseña quieres cambiar")
            else:
                id_ = int(c[1])
                api.change_password(id_)
        elif cmd == "quit":
            return
        else:
            api.help()

if __name__ == "__main__":
    main()
