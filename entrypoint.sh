#!/bin/sh
set -e

echo "Waiting for DB..."
while ! python -c "
import socket, sys, os
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.connect((os.environ.get('DB_HOST','db'), int(os.environ.get('DB_PORT','5432'))))
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
  sleep 1
done
echo "DB is ready."

echo "Making migrations..."
python manage.py makemigrations --noinput

echo "Running migrations..."
python manage.py migrate --noinput

echo "Starting: $@"
exec "$@"
