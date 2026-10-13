"""
AIoT Forest Protection - Root database_manager proxy
Memungkinkan modul/skrip di root mengimpor DatabaseManager secara langsung.
"""
import os
import sys

backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "python_backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from python_backend.database_manager import DatabaseManager

__all__ = ["DatabaseManager"]
