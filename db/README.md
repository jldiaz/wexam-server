# Componente: base de datos PostreSQL

El Dockerfile se basa en el de `postgres:alpine` y simplemente se añade un script para que cree las bases de datos de la aplicación cuando arranque.

## Crear imagen del contenedor

```
docker build -t wexam-db-img:latest .
```

## Lanzar contenedor:

```
docker run --rm --name wexam-db -e POSTGRES_PASSWORD=mysecretpassword -d wexam-db-img
```

Tendrá creada las bases de datos "wexam" y "wexam_test", ambas vacías (y sin usuarios)

## Conectarse al contenedor

Desde fuera de un contenedor se puede conectar si se conoce su IP, que se puede averiguar con:

```
docker inspect wexam-db|grep IP
```

La IP que se obtenga se copia al archivo `../wexam/settings/uniovi-redis-postgres.yml` en una sección como la siguiente:

```yaml
database:
  provider: postgres
  user: postgres
  password: mysecretpassword
  host: 172.17.0.5
  database: wexam
  filename: null
  create_db: null
```

Podemos poner como base de datos wexam o wexam_test. La contraseña `mysecretpassword` debe coincidir con la que se usó para lanzar el contenedor. El archivo donde figura la clave verdadera no debe estar bajo control de versiones.

Cuando la aplicación morepath esté "conteinarizada", no necesitaremos esa IP y podremos poner en su lugar el nombre del contenedor donde corre postgres, es decir `wexam-db` según el ejemplo anterior.


## Creación de usuarios

La base de datos cuando arranca está vacía. Para crear al primer usuario (admin) usar el script `../wexam/seed_admin.py`. Requiere ciertas variables de entorno: una que le diga que use el entorno de producción (para que conecte con la base de datos postgres) y otras con el email y clave del nuevo usuario. Ej:

```
RUN_ENV=uniovi-redis-postgres WEXAM_ADMIN_EMAIL=jldiaz@uniovi.es WEXAM_ADMIN_PASSWORD=clavesupersecreta python seed_admin.py
```

Esto conecta con la BD y crea a ese usuario con permisos de admin. Si el usuario (email) ya existía, fracasará, pero en el primer arranque no hay ningún usuario aún por lo que debería funcionar.

Tabién puede hacerse en teoría conectando "a pelo" con el servidor de la base de datos y metiendo SQL, pero ya que las claves se almacenan hasheadas no es fácil crear un usuario de este modo, aunque sí es fácil eliminar uno:

```
$ docker exec -it wexam-db bash
root@3225522c6ac4:/# psql -U postgres wexam
wexam=# select * from profesor;
 id | nombre  |      email       | username |                           password                           |   role   |       fecha_creacion
      |     fecha_modificacion
----+---------+------------------+----------+--------------------------------------------------------------+----------+----------------------
------+----------------------------
  1 | Admin   | jldiaz@uniovi.es | admin    | $2b$12$Mf/ir2hH.Rwv4/RE4OsKSeZUMPqBe1FOGpuKFurS7lfC76aVTiU.q | admin    | 2018-06-18 18:07:54.6
58062 | 2018-06-18 18:07:54.658062
  2 | JL Diaz | jldiaz@gmail.com |          | $2b$12$0yCDx3MCUHb/3WwDwW6mW.7.JsP.mY5jtMMFxRCo.pDORT49zKHUS | profesor | 2018-06-18 18:12:02.3
61524 | 2018-06-18 18:12:02.361547
(2 rows)
wexam=# DELETE FROM profesor WHERE id=2;
```

Una vez creado ADMIN, el resto de usuarios se pueden crear haciendo que ADMIN haga POST a la ruta `/profesores`. No he hecho aún un cliente para esto, pero puede hacerse desde línea de comandos así:

```
# Arrancar al servidor (si no estaba arrancado), por ejemplo con el server de desarrollo
RUN_ENV=uniovi-redis-postgres run-app &
# Hacer login de admin
http --headers --json POST :5000/login email=jldiaz@uniovi.es password=clavesupersecreta |grep ^Auth > token
# Crear un nuevo usuario (debe usarse el token obtenido en el apartado anterior)
http --json POST :5000/profesores nombre="Jose" email=jldiaz@gmail.com password=0000 role=profesor "`cat token`"
```

## Persistencia

La base de datos existe dentro del contenedor. Si éste muere, la base de datos se pierde. Para evitarlo hay que montar un volumen, pero aún no he mirado cómo se hace.


# Despliegue en Heroku

Para que en Heroku use también Postgres, basta poner en el archivo de configuración (`../settings/heroku-postgres.yaml`):

```
database:
  provider: heroku
```

pues de esa forma en la inicialización de la aplicación se usará la variable de entorno `DATABASE_URL` para extraer de ella los datos de conexión con la base de datos (esa variable la crea Heroku y no tenemos control sobre ella).

Sólo hay que decir a heroku que use el fichero de configuración apropiado, mediante:

```
heroku config:set RUN_ENV=heroku-postgres
```

Y desplegar la aplicación con `git push heroku`.

## Creación de usuarios en heroku

La base de datos empieza vacía. El primer usuario (admin) se crea entrando en la máquina y ejecutando el script linux, de forma similar a como se explicó en el contenedor docker. En este caso:

```
$ heroku run bash   # Para entrar en la máquina
~ $ cd wexam
~ $ WEXAM_ADMIN_EMAIL=jldiaz@gmail.com WEXAM_ADMIN_PASSWORD=clavesupersecreta python seed_admin.py
~ $ exit
```

Y ya desde cualquier otro sitio, haciando POST a `/profesores` se pueden crear otros. Por ejemplo:

```
# Hacer login en la app, como admin
$ http --headers --json POST https://wexam.herokuapps.com/login email=jldiaz@gmail.com password=clavesupersecreta |grep ^Auth > token
# Crear un nuevo usuario (debe usarse el token obtenido en el apartado anterior)
$ http --json POST https://wexam.herokuapps.com/profesores nombre="Jose Luis Diaz" email=jldiaz@uniovi.es password=0000 role=profesor "`cat token`"
# Borrar token por si acaso
$ rm token
```

## Backup de la base de datos de heroku

Referencia: <https://devcenter.heroku.com/articles/heroku-postgres-backups>

```
heroku pg:backups:capture
```

O para tener una copia local:

```
heroku pg:backups:download
```


### Copiar el dump a mi base de datos

Por si decido abandonar Heroku, una vez he bajado un dump de la base de datos puedo metérselo a mi Postgres local (conteinerizado) mediante:

```
# Conectar con el contenedor en ejecución y lanzar bash, montando en /tmp la carpeta actual
# que contiene el dump de la bbdd
$ docker run --rm -it --link wexam-db:postgres --volume $PWD/:/tmp/ wexam-db-image bash
# Restaurar ese dump
# pg_restore -h postgres -U postgres -d wexam /tmp/latest.dump
```

Da muchos errores por ciertos roles (cosas de heroku/amazon) no presentes en la bbdd, pero al final parece que la información importante sí que está.
