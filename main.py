#!/usr/bin/env python3
"""MedTrace entry point:  python main.py   (reads input.json, writes output.json)"""
import sys

from medtrace.runner import main

if __name__ == "__main__":
    sys.exit(main())
