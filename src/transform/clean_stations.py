"""
Pipeline that reads raw snapshots,  cleans attributes, creates geometries,
projects to California Albers, and writes fast processed files
"""

import sys
from pathlib import Path
import pandas as pd

# Allow running from terminal without depending on CWD
sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import RAW_DIR, TODAY_STR, CENSUS_API_KEY

def find_latest_file():

def clean_ev_station():

def clean_gas_station():
