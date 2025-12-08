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

"""MiniMax TTS model definitions and types."""

from typing import Literal

# MiniMax TTS models
# Reference: https://platform.minimax.io/docs/api-reference/speech-t2a-http
TTSModels = Literal[
    "speech-2.6-hd",      # High definition model (latest)
    "speech-2.6-turbo",   # Fast model (latest)
    "speech-02-hd",       # High definition model
    "speech-02-turbo",    # Fast model
    "speech-01-hd",       # High definition model (legacy)
    "speech-01-turbo",    # Fast model (legacy)
]

# Supported audio formats
TTSAudioFormat = Literal[
    "mp3",    # MP3 format (streaming supported)
    "wav",    # WAV format (non-streaming only)
    "flac",   # FLAC format (non-streaming only)
]

# Supported languages for language_boost
TTSLanguages = Literal[
    "Chinese",
    "Chinese,Yue",  # Cantonese
    "English",
    "Arabic",
    "Russian",
    "Spanish",
    "French",
    "Portuguese",
    "German",
    "Turkish",
    "Dutch",
    "Ukrainian",
    "Vietnamese",
    "Indonesian",
    "Japanese",
    "Italian",
    "Korean",
    "Thai",
    "Polish",
    "Romanian",
    "Greek",
    "Czech",
    "Finnish",
    "Hindi",
    "auto",  # Auto-detect
]

# Sound effects
TTSSoundEffects = Literal[
    "spacious_echo",
    "none",
]

# Default values
DEFAULT_MODEL: TTSModels = "speech-02-turbo"
DEFAULT_SAMPLE_RATE = 32000
DEFAULT_AUDIO_FORMAT: TTSAudioFormat = "mp3"
DEFAULT_BITRATE = 128000
DEFAULT_SPEED = 1.0
DEFAULT_VOLUME = 1.0
DEFAULT_PITCH = 0

# Default voice ID - MiniMax predefined voices
# See: https://platform.minimax.io/docs/guides/speech-t2a-voices
DEFAULT_VOICE_ID = "male-qn-qingse"

# API endpoints
MINIMAX_TTS_HTTP_URL = "https://api.minimax.io/v1/t2a_v2"
# Alternative endpoint with reduced TTFA (Time to First Audio)
MINIMAX_TTS_HTTP_URL_FAST = "https://api-uw.minimax.io/v1/t2a_v2"
