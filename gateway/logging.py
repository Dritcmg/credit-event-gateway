import json
import logging


class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {"level": record.levelname, "event": record.getMessage()}
        for name in ("request_id", "route", "status_code", "duration_ms"):
            if hasattr(record, name):
                data[name] = getattr(record, name)
        return json.dumps(data)


def configure():
    logger = logging.getLogger("credit_gateway")
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
