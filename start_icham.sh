#!/bin/bash
cd "$(dirname "$0")"
echo "Démarrage Naali Planner — Icham Benaissa (port 5002)"
python3 web/app.py --port 5002 --profile icham
