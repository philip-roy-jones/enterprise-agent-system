import argparse
import logging


def main(argv=None):
    parser = argparse.ArgumentParser(prog="enterprise-harness")
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from eas_harness.worker import run_worker

    run_worker()
