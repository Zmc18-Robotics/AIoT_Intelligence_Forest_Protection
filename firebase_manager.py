"""
AIoT Forest Protection - Root firebase_manager proxy
"""
import os
import sys

backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "python_backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from python_backend.firebase_manager import FirebaseManager

__all__ = ["FirebaseManager"]
