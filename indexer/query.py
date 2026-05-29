"""Stub — actual implementation moved to server/query.py."""
import runpy
import os
import sys

_server_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server")
_target = os.path.join(_server_dir, "query.py")
runpy.run_path(_target, run_name="__main__")
