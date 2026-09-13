"""Provider-neutral records; preserve replay metadata at the adapter boundary."""
from enum import Enum


class ResponseRecord:
    def __init__(self, values):
        self.values = values

    def __getattr__(self, name):
        if name not in self.values:
            raise AttributeError(name)
        return normalize_response(self.values[name])

    def model_dump(self, *, exclude_none=False):
        return {name: value for name, value in self.values.items()
                if not exclude_none or value is not None}


def plain_value(value):
    if isinstance(value, ResponseRecord):
        return value.values
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_value(item) for item in value]
    if hasattr(value, "model_dump"):
        return plain_value(value.model_dump(exclude_none=False))
    if hasattr(value, "__dict__"):
        return {key: plain_value(item) for key, item in vars(value).items()
                if not key.startswith("_")}
    return value


def normalize_response(value):
    if isinstance(value, ResponseRecord):
        return value
    value = plain_value(value)
    if isinstance(value, dict):
        return ResponseRecord(value)
    if isinstance(value, list):
        return [normalize_response(item) for item in value]
    return value


class NormalizedStream:
    def __init__(self, stream):
        self.stream = stream

    async def __aenter__(self):
        await self.stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.stream.__aexit__(*args)

    def __aiter__(self):
        return self

    async def __anext__(self):
        return normalize_response(await self.stream.__anext__())
