Aquí se implementa una interfaz de línea de comandos administrativa
que permite crear usuarios, cambiarles la clave, o borrarlos.

Para que funcione es necesario que exista un usuario con rol "admin"
en la base de datos y conocer su nombre de usuario y contraseña.

Para ejecutar el programa conviene crear un entorno virtual (python3)
en el cual instalar los paquetes necesarios mediante:

    pip install requirements.txt

y después:

    python admin.py --help


