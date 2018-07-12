FROM python:3.6

# RUN apt-get update && apt-get install -y pandoc \
#    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app
COPY requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY . .

# Instalar dependencias del proyecto wexam
RUN pip install -e .

EXPOSE 29000

# Lanza el servidor uwsgi
CMD [ "./lanzar-uwsgi.sh" ]
