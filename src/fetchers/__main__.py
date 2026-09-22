import sys

from src.fetchers import TARGET, run_fetcher_test

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else TARGET
    run_fetcher_test(target)