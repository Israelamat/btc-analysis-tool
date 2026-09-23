"""Project entry point: fetch APIs, light analytics and buy actions.

All the logic lives in src/fetchers/pipeline.py so this file stays minimal.
"""

from src.fetchers.pipeline import run_pipeline

if __name__ == "__main__":
    run_pipeline()