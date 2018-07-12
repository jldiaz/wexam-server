# Creación del contenedor

```
docker build -t wexam-app:latest .
```

# Arranque del contenedor

```
docker run --rm -d --link wexam-redis:redis --link wexam-db:wexam-db --name wexam-app -v `pwd`:/usr/src/app -p 29000:29000 -e RUN_ENV=uniovi-redis-docker wexam-app
```

Donde:

* `wexam-redis` es el nombre del contenedor que está ejecutando redis (y `redis` es el nombre por el que la app intentará conectar)
* `wexam-db` es el nombre del contenedor que está ejecutando postgres
* `wexam-app` es el nombre este contenedor que estamos lanzando (y de la imagen desde el que lo creamos)
* `-v` sirve para montar la carpeta actual en el contenedor, y poder seguir desarrollando "en vivo"
* `-p ` redirige el puerto 29000 del anfitrión al 29000 del contenedor, donde escucha uwsgi
* `-e` sirve para pasarle variables de entorno