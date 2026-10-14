#!/bin/sh
Xvfb :99 -screen 0 1920x1200x24 -nolisten tcp >/dev/null 2>&1 &
sleep 1; export DISPLAY=:99
exec python -u /w/film.py "$@"
