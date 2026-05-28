#!/bin/bash
cd "$(dirname "$0")"
echo "Démarrage Naali Planner — Amir Ounissi (port 5001)"
python3 web/app.py --port 5001
