"""
Launcher untuk script kalibrasi area dan sudut servo (0° - 90°).
Menjalankan python_backend/calibrate_zones.py
"""
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "python_backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from calibrate_zones import main

if __name__ == "__main__":
    main()
