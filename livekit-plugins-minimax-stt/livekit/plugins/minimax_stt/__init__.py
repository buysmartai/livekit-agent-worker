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

"""MiniMax STT plugin for LiveKit Agents

This plugin provides speech-to-text (STT) capabilities using MiniMax's
streaming ASR (Automatic Speech Recognition) API.

Environment variables:
- `MINIMAX_API_KEY`: Your MiniMax API key (required)
- `MINIMAX_GROUP_ID`: Your MiniMax Group ID (optional, for some API versions)
"""

from .stt import STT, SpeechStream
from .version import __version__

__all__ = ["STT", "SpeechStream", "__version__"]

from livekit.agents import Plugin

from .log import logger


class MiniMaxSTTPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)


Plugin.register_plugin(MiniMaxSTTPlugin())

# Hide internal modules from documentation
_module = dir()
NOT_IN_ALL = [m for m in _module if m not in __all__]

__pdoc__ = {}

for n in NOT_IN_ALL:
    __pdoc__[n] = False
