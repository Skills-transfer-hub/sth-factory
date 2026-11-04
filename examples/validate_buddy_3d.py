"""Compatibility entry point: the cockpit now has one Buddy per task."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).with_name('validate_factory_floor.py')),run_name='__main__')
