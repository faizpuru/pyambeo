# pyambeo

Async Python client for Sennheiser AMBEO soundbars (Max, Plus and Mini), built on `aiohttp`.

It powers the [AMBEO Soundbar integration](https://github.com/faizpuru/ha-ambeo_soundbar) for Home Assistant, but does not depend on it.

## Installation

```bash
pip install pyambeo
```

## Usage

```python
import asyncio

import aiohttp

from pyambeo import AmbeoSoundbar


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        # Detects the model and returns the matching implementation.
        bar = await AmbeoSoundbar.connect("192.168.1.10", session)
        print(bar.info)

        state = await bar.fetch_state()
        print(state)

        await bar.set_volume(20)

        # Push updates from the device.
        async for updates in bar.listen():
            print(updates)


asyncio.run(main())
```

The caller owns the `aiohttp.ClientSession`. All errors raised by the library inherit from `AmbeoError`:

| Exception | Meaning |
|---|---|
| `AmbeoConnectionError` | The device cannot be reached |
| `AmbeoTimeoutError` | A request timed out (subclass of `AmbeoConnectionError`) |
| `AmbeoResponseError` | The device answered with an unexpected response |
| `AmbeoUnsupportedModelError` | The device model is not supported |

## Supported devices

| Model | Class |
|---|---|
| AMBEO Soundbar Max | `AmbeoEspresso` |
| AMBEO Soundbar Plus | `AmbeoPopcorn` |
| AMBEO Soundbar Mini | `AmbeoPopcorn` |

## Development

```bash
uv run --group dev pytest
uv run --group dev ruff check .
```

## License

MIT
