#!/usr/bin/env python3
"""Setup script for AMSKY01 package."""

from setuptools import setup

# Read version from version.py to avoid import issues in isolated builds
version_ns = {}
with open("version.py", "r", encoding="utf-8") as f:
    exec(f.read(), version_ns)
setup(version=version_ns.get("__version__"))
