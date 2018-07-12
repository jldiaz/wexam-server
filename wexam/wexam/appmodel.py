"""Declara clases necesarias para las rutas que no representan directamente
entidades de la base de datos (como /login, /reset_password, etc.)"""

import datetime
from smtplib import SMTP, SMTP_SSL
import ssl
from email.mime.text import MIMEText
from email.header import Header
import jwt


class Root(object):     # pylint: disable=too-few-public-methods
    """Ruta raiz"""
    pass


class Login(object):    # pylint: disable=too-few-public-methods
    """Ruta para identificarse ante el sistema y obtener el JWT"""
    pass

class ResetDB(object):   # pylint: disable=too-few-public-methods
    """Ruta para restaurar la base de datos a una colección de exámenes de ejemplo"""
    pass

class ResetPassword(object):
    """Clase que agrupa las funciones relacionadas con cambiar la clave
    de forma segura mediante un enlace enviado por email al usuario"""
    def __init__(self, quien):
        self.quien = quien
        self.email = quien.email

    def envia_enlace_reiniciar_clave(self, url_base, settings):
        """Genera un JWT "de un solo uso" y lo usa para construir una URL
        que envía por email al usuario que quiere cambiar su clave"""

        # No hay tal cosa como JWT de un solo uso, ya que el JWT es sin
        # estado. No obstante, he dado con una interesante idea en
        # https://www.jbspeakr.cc/howto-single-use-jwt/
        # que es la siguiente:
        #
        # El JWT se "firma" usando como secreto la clave del usuario en
        # cuestión (en realidad su hash que es lo que almacena
        # la base de datos)
        #
        # Cuando el usuario visite ese enlace, se intentará descifrar el token
        # usando como secreto su clave (hash) y si no la ha cambiado se
        # decodificará sin problemas. Si ya la ha cambiado, no decodificará
        # bien y por tanto el token se rechaza. Por tanto sólo puede usarse
        # para cambiar la clave una vez ¡brillante!
        ahora = datetime.datetime.utcnow()
        token = jwt.encode(
            {
                "email": self.quien.email,
                "iat": ahora,
                "nbf": ahora,
                "exp": ahora + datetime.timedelta(minutes=15),
            },  # Contenido del jwt
            self.quien.password,  # clave de cifrado
            'HS256'               # Algoritmo
            )

        msg = self.crear_mensaje(nombre=self.quien.nombre.split()[0],
                                 url_base=url_base,
                                 token=token.decode("ascii"))
        self.send_email(toaddr=self.quien.email,
                        mensaje=msg, settings=settings)
        print("Esto debería ser enviado por email a {}\n\n{}"
              .format(self.quien.email, msg))

    @staticmethod
    def crear_mensaje(nombre, url_base, token):
        """Compone el mensaje que se enviará al usuario"""
        return (
            "Hola {}!\n"
            "\n"
            "Gracias por usar WeXaM. Si quieres cambiar tu contraseña "
            "pulsa en el siguiente enlace "
            "(expirará dentro de 15 minutos):\n"
            "\n"
            "{}?token={}\n"
            "\n"
            "Si no has solicitado un cambio de contraseña en nuestro "
            "servicio, simplemente ignora este mensaje.\n"
            .format(nombre, url_base, token)
            )

    def validate_token(self, token):
        """Comprueba la firma del token y que el email que contiene
        sea correcto"""
        try:
            claims = jwt.decode(token, self.quien.password, ['HS256'])
        except jwt.InvalidTokenError as exception:
            # El token ni siquiera es un jwt
            print("Token no es decodifica", exception)
            return False
        if claims["email"] != self.quien.email:
            raise TypeError("El token no es del email en la ruta")
        return True

    @staticmethod
    def send_email(toaddr, mensaje, settings):
        """Envía un mensaje por el protocolo SMTP. Los datos del servidor
        smtp los obtiene de la configuración global, así como el remite que ha
        de usarse para el mensaje."""
        server = settings.email.smtp_server
        if "no enviar" in server:
           print("MENSAJE QUE SE ENVIARIA:")
           print(mensaje)
           return
        fromaddr = settings.email.from_addr
        port = settings.email.smtp_port
        msg = MIMEText(mensaje, _charset="UTF-8")
        msg['From'] = fromaddr
        msg['To'] = toaddr
        msg['Subject'] = Header("WeXaM. Reinicio de contraseña", "utf-8")
        if hasattr(settings.email, "usetls") and settings.email.usetls:
           print("Conectando con servidor de correo")
           smtp = SMTP(server, port)
           smtp.ehlo()
           print("Conectado. Activando TLS")
           smtp.starttls()
           smtp.ehlo()
           print("Activado. Autentiandose")
           smtp.login(getattr(settings.email, "user", "anonymous"),
                      getattr(settings.email, "password", ""))
           print("Autenticado. Enviando mensaje")
        else:
           smtp = SMTP(server, port)
        # smtp.set_debuglevel(1)
        smtp.sendmail(fromaddr, toaddr, msg.as_string())
        smtp.quit()
        smtp.close()
