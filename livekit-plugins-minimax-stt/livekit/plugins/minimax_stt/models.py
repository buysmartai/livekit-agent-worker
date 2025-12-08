# Copyright 2025 BuySmartAI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""MiniMax STT model definitions and types."""

from typing import Literal

# MiniMax ASR models
# Reference: https://platform.minimaxi.com/document/Speech%20Recognition
STTModels = Literal[
    "speech-01",  # Standard model
]

# Supported audio encodings
STTEncoding = Literal[
    "pcm",      # Raw PCM audio
    "wav",      # WAV format
    "mp3",      # MP3 format
]

# Supported languages
STTLanguages = Literal[
    "zh",       # Chinese
    "en",       # English
    "ja",       # Japanese
    "ko",       # Korean
    "auto",     # Auto-detect
]

# Default values
DEFAULT_MODEL = "speech-01"
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_ENCODING = "pcm"
DEFAULT_LANGUAGE = "zh"

# API endpoints
# Note: These may need to be updated based on MiniMax's actual API documentation
MINIMAX_ASR_WS_URL = "wss://api.minimax.chat/v1/audio/asr/stream"
MINIMAX_ASR_HTTP_URL = "https://api.minimax.chat/v1/audio/asr"
