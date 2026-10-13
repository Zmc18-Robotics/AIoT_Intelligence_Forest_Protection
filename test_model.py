"""
=======================================================================
 Launcher untuk Live Model Testing & Visualisasi Sudut Servo 0° - 90°
 Menjalankan python_backend/test_model.py
=======================================================================
"""
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "python_backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import test_model

if __name__ == "__main__":
    test_model.main()
