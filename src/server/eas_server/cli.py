import argparse
import logging


def main(argv=None):
    parser = argparse.ArgumentParser(prog="enterprise-server")
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    import uvicorn
    from eas_server.config import Settings

    settings = Settings()
    uvicorn.run(
        "eas_server.backend:create_app",
        factory=True,
        host=settings.bind_host,
        port=settings.bind_port,
        access_log=False,
        timeout_graceful_shutdown=5,
    )
