import argparse
import logging
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(prog="enterprise")
    parser.add_argument(
        "command", choices=["serve", "worker", "dev", "demo", "improve", "review", "deploy", "rollback"]
    )
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if options.command == "serve":
        import uvicorn

        uvicorn.run(
            "enterprise.backend:create_app", factory=True, host="127.0.0.1", port=8000, access_log=False
        )
    elif options.command == "worker":
        from .worker import run_worker

        run_worker()
    elif options.command == "dev":
        backend = subprocess.Popen([sys.executable, "-m", "enterprise.cli", "serve"])
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
            worker = subprocess.Popen([sys.executable, "-m", "enterprise.cli", "worker"])
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
        from .demo import main as demo

        demo(options.args)
    else:
        from .improve import main as improve

        improve([options.command] + options.args)


if __name__ == "__main__":
    main()
