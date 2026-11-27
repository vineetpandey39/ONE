"""Bootstrap the company governor using the actual local source checkout."""
import os
from pathlib import Path
import sys

source = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(source))
os.environ['PYTHONPATH'] = str(source) + os.pathsep + os.environ.get('PYTHONPATH', '')

from openjarvis.one_agents.daily_governor import main

if __name__ == '__main__':
    main()
