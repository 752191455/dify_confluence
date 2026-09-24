import yaml
import argparse
from scheduler import run_scheduler

def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    run_scheduler(config, args.config)