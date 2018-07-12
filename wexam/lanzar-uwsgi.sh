#!/bin/bash
pip install -e .
MOUNT=${API_MOUNT_PATH:=/wexam-api}
uwsgi --mount $MOUNT=wsgi:app --manage-script-name  --master --pidfile=/tmp/project-master.pid --socket=0.0.0.0:29000 --stats 127.0.0.1:9191 --processes 2 --threads 2
