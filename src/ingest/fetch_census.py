"""
Gets Census and Demographics Data using Census APIs
(for measuring equity)
"""
import requests
import pandas as pd

def fetch_acs_ca_demographics_2024(output_path):
    api_url = "https://api.census.gov/data/2024/acs/acs5"

    params = {
        "get": "NAME,B01003_001E,B19013_001E", # Name, Total Population, Median Household Income
        "for": "tract: *",
        "in": "state:06", # Filter to California
    }
    print(f"Fetching 2024 ACS California 5-year demographics...")
    response = requests.get(api_url, params=params)
    response.raise_for_status()

    data = response.json()
    df = pd.DataFrame(data[1:], columns = data[0])

    # Rename column names
    df = df.rename(columns={'B01003_001E': 'total_population',
                            'B19013_001E': 'median_income'})

    # Construct GEOID
    df["GEOID"] = df["state"] + df["county"] + df["tract"]

    # Clean data types
    df["total_population"] = pd.to_numeric(df["total_population"], errors='coerce').fillna(0).astype(int)
    df["median_income"] = pd.to_numeric(df["median_income"], errors="coerce")

    df.to_csv(output_path, index=False)
    print(f"Success! Saved California 2024 ACS 5-year ACS demographiccs to {output_path}")

    
    