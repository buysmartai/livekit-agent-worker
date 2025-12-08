# LiveKit Plugins MiniMax TTS

MiniMax Text-to-Speech plugin for LiveKit Agents.

## Installation

```bash
pip install livekit-plugins-minimax-tts
```

Or install from source:

```bash
cd livekit-plugins-minimax-tts
pip install -e .
```

## Usage

```python
from livekit.plugins.minimax_tts import TTS

tts = TTS(
    model="speech-02-turbo",  # or speech-2.6-turbo, speech-2.6-hd
    voice_id="male-qn-qingse",  # MiniMax voice ID
    # api_key="your_api_key",  # or set MINIMAX_API_KEY env var
)
```

## Environment Variables

- `MINIMAX_API_KEY`: Your MiniMax API key (required)

## Supported Models

- `speech-2.6-hd` - High definition model
- `speech-2.6-turbo` - Fast model
- `speech-02-hd` - High definition model (v2)
- `speech-02-turbo` - Fast model (v2)
- `speech-01-hd` - High definition model (v1)
- `speech-01-turbo` - Fast model (v1)

## API Reference

See [MiniMax T2A API Documentation](https://platform.minimax.io/docs/api-reference/speech-t2a-http)
