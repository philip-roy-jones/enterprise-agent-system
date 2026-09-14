import argparse
import logging
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(prog="enterprise")
    parser.add_argument(
        "command",
        choices=[
            "serve",
            "worker",
            "dev",
            "demo",
            "learning-demo",
            "longitudinal-demo",
        ],
    )
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if options.command == "serve":
        from eas_server.cli import main as serve

        serve(options.args)
    elif options.command == "worker":
        from eas_harness.cli import main as worker

        worker(options.args)
    elif options.command == "dev":
        backend = subprocess.Popen([sys.executable, "-m", "eas_server"])
        worker = None
        try:
            import httpx

            for _ in range(50):
                try:
                    if httpx.get("http://127.0.0.1:8000/api/health").is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("Backend did not become healthy")
            worker = subprocess.Popen([sys.executable, "-m", "eas_harness"])
            print(
                "\nEnterprise Agent System: http://127.0.0.1:8000\nCtrl+C stops both processes.\n", flush=True
            )
            while backend.poll() is None and worker.poll() is None:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            if worker:
                worker.terminate()
                worker.wait(timeout=15)
            backend.terminate()
            backend.wait(timeout=15)
    elif options.command == "demo":
        from enterprise_dev.demo import main as demo

        demo(options.args)
    elif options.command == "learning-demo":
        from enterprise_dev.learning_demo import main as learning_demo

        learning_demo(options.args)
    elif options.command == "longitudinal-demo":
        from enterprise_dev.longitudinal_demo import main as longitudinal_demo

        longitudinal_demo(options.args)


if __name__ == "__main__":
    main()
