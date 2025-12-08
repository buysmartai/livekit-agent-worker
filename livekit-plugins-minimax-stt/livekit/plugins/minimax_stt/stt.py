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

"""MiniMax Streaming Speech-to-Text implementation.

This module provides STT and SpeechStream classes for real-time
speech recognition using MiniMax's ASR API over WebSocket.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import weakref
from dataclasses import dataclass, replace
from typing import Any, Literal

import aiohttp

from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    stt,
    utils,
)
from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer, is_given

from .log import logger
from .models import (
    DEFAULT_ENCODING,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    DEFAULT_SAMPLE_RATE,
    MINIMAX_ASR_WS_URL,
    STTEncoding,
    STTLanguages,
    STTModels,
)


@dataclass
class STTOptions:
    """Configuration options for MiniMax STT."""

    model: str
    language: str
    sample_rate: int
    encoding: str
    api_key: str
    group_id: str | None
    base_url: str
    # VAD (Voice Activity Detection) options
    vad_enabled: bool
    vad_threshold: float
    vad_min_silence_duration_ms: int
    # Buffer settings
    buffer_size_seconds: float


class STT(stt.STT):
    """MiniMax Streaming Speech-to-Text.

    Uses MiniMax's ASR WebSocket API for real-time speech recognition.

    Args:
        model: The ASR model to use. Defaults to "speech-01".
        language: The language for recognition. Defaults to "zh" (Chinese).
        sample_rate: Audio sample rate in Hz. Defaults to 16000.
        encoding: Audio encoding format. Defaults to "pcm".
        api_key: MiniMax API key. Falls back to MINIMAX_API_KEY env var.
        group_id: MiniMax Group ID. Falls back to MINIMAX_GROUP_ID env var.
        base_url: WebSocket base URL for the API.
        vad_enabled: Enable Voice Activity Detection. Defaults to True.
        vad_threshold: VAD sensitivity threshold. Defaults to 0.5.
        vad_min_silence_duration_ms: Minimum silence duration for VAD. Defaults to 500.
        buffer_size_seconds: Audio buffer size in seconds. Defaults to 0.1.
        http_session: Optional aiohttp ClientSession to reuse.
    """

    def __init__(
        self,
        *,
        model: STTModels | str = DEFAULT_MODEL,
        language: STTLanguages | str = DEFAULT_LANGUAGE,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        encoding: STTEncoding | str = DEFAULT_ENCODING,
        api_key: str | None = None,
        group_id: str | None = None,
        base_url: str = MINIMAX_ASR_WS_URL,
        vad_enabled: bool = True,
        vad_threshold: float = 0.5,
        vad_min_silence_duration_ms: int = 500,
        buffer_size_seconds: float = 0.1,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,
                interim_results=True,
            ),
        )

        # Resolve API key from environment if not provided
        api_key = api_key or os.environ.get("MINIMAX_API_KEY")
        if not api_key:
            raise ValueError(
                "MiniMax API key is required. "
                "Set MINIMAX_API_KEY environment variable or pass api_key parameter."
            )

        group_id = group_id or os.environ.get("MINIMAX_GROUP_ID")

        self._opts = STTOptions(
            model=model,
            language=language,
            sample_rate=sample_rate,
            encoding=encoding,
            api_key=api_key,
            group_id=group_id,
            base_url=base_url,
            vad_enabled=vad_enabled,
            vad_threshold=vad_threshold,
            vad_min_silence_duration_ms=vad_min_silence_duration_ms,
            buffer_size_seconds=buffer_size_seconds,
        )

        self._session = http_session
        self._streams: weakref.WeakSet[SpeechStream] = weakref.WeakSet()

    def _ensure_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None:
            self._session = utils.http_context.http_session()
        return self._session

    @property
    def session(self) -> aiohttp.ClientSession:
        """Get the aiohttp session."""
        return self._ensure_session()

    @property
    def model(self) -> str:
        """Get the current model name."""
        return self._opts.model

    @property
    def provider(self) -> str:
        """Get the provider name."""
        return "MiniMax"

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.SpeechEvent:
        """Single-shot recognition is not implemented.

        Use stream() for real-time streaming recognition.
        """
        raise NotImplementedError(
            "Single-shot recognition is not supported by MiniMax STT. "
            "Use stream() for streaming recognition."
        )

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "SpeechStream":
        """Create a streaming speech recognition session.

        Args:
            language: Override the default language for this stream.
            conn_options: Connection options for timeout and retry settings.

        Returns:
            SpeechStream: A streaming speech recognition session.
        """
        config = replace(self._opts)
        if is_given(language):
            config.language = language

        stream = SpeechStream(
            stt=self,
            opts=config,
            conn_options=conn_options,
            http_session=self.session,
        )
        self._streams.add(stream)
        return stream

    def update_options(
        self,
        *,
        model: NotGivenOr[str] = NOT_GIVEN,
        language: NotGivenOr[str] = NOT_GIVEN,
        vad_enabled: NotGivenOr[bool] = NOT_GIVEN,
        vad_threshold: NotGivenOr[float] = NOT_GIVEN,
        vad_min_silence_duration_ms: NotGivenOr[int] = NOT_GIVEN,
        buffer_size_seconds: NotGivenOr[float] = NOT_GIVEN,
    ) -> None:
        """Update STT options.

        Changes will apply to new streams created after this call.
        """
        if is_given(model):
            self._opts.model = model
        if is_given(language):
            self._opts.language = language
        if is_given(vad_enabled):
            self._opts.vad_enabled = vad_enabled
        if is_given(vad_threshold):
            self._opts.vad_threshold = vad_threshold
        if is_given(vad_min_silence_duration_ms):
            self._opts.vad_min_silence_duration_ms = vad_min_silence_duration_ms
        if is_given(buffer_size_seconds):
            self._opts.buffer_size_seconds = buffer_size_seconds

        # Update existing streams
        for stream in self._streams:
            stream.update_options(
                language=language,
                vad_threshold=vad_threshold,
                buffer_size_seconds=buffer_size_seconds,
            )

    async def aclose(self) -> None:
        """Close the STT instance and cleanup resources."""
        for stream in list(self._streams):
            await stream.aclose()
        self._streams.clear()


class SpeechStream(stt.SpeechStream):
    """MiniMax streaming speech-to-text session.

    Handles WebSocket connection to MiniMax ASR API and processes
    audio frames in real-time.
    """

    # Message to close the WebSocket connection
    _CLOSE_MSG: str = json.dumps({"type": "close"})

    def __init__(
        self,
        *,
        stt: STT,
        opts: STTOptions,
        conn_options: APIConnectOptions,
        http_session: aiohttp.ClientSession,
    ) -> None:
        super().__init__(
            stt=stt,
            conn_options=conn_options,
            sample_rate=opts.sample_rate,
        )

        self._opts = opts
        self._session = http_session
        self._speech_duration: float = 0.0
        self._speaking = False

        # Reconnection support
        self._reconnect_event = asyncio.Event()
        self._ws: aiohttp.ClientWebSocketResponse | None = None

        # Track final transcripts for combining
        self._final_events: list[stt.SpeechEvent] = []

    def update_options(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        vad_threshold: NotGivenOr[float] = NOT_GIVEN,
        buffer_size_seconds: NotGivenOr[float] = NOT_GIVEN,
    ) -> None:
        """Update stream options (triggers reconnection)."""
        if is_given(language):
            self._opts.language = language
        if is_given(vad_threshold):
            self._opts.vad_threshold = vad_threshold
        if is_given(buffer_size_seconds):
            self._opts.buffer_size_seconds = buffer_size_seconds

        # Trigger reconnection to apply new settings
        self._reconnect_event.set()

    async def _run(self) -> None:
        """Main loop for streaming transcription."""
        closing_ws = False

        @utils.log_exceptions(logger=logger)
        async def send_task(ws: aiohttp.ClientWebSocketResponse) -> None:
            """Send audio frames to the WebSocket."""
            nonlocal closing_ws

            # Create audio byte stream for buffering
            audio_bstream = utils.audio.AudioByteStream(
                sample_rate=self._opts.sample_rate,
                num_channels=1,
                samples_per_channel=int(
                    self._opts.sample_rate * self._opts.buffer_size_seconds
                ),
            )

            async for ev in self._input_ch:
                if isinstance(ev, self._FlushSentinel):
                    # Flush remaining audio
                    frames = audio_bstream.flush()
                    for frame in frames:
                        await self._send_audio_frame(ws, frame)
                    continue

                # Process audio frame
                frames = audio_bstream.push(ev.data)
                for frame in frames:
                    self._speech_duration += frame.duration
                    await self._send_audio_frame(ws, frame)

            # Signal end of stream
            closing_ws = True
            await ws.send_str(self._CLOSE_MSG)

        @utils.log_exceptions(logger=logger)
        async def recv_task(ws: aiohttp.ClientWebSocketResponse) -> None:
            """Receive and process transcription results."""
            nonlocal closing_ws

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        self._process_message(data)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Failed to parse WebSocket message: %s", msg.data
                        )
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("WebSocket error: %s", ws.exception())
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    if not closing_ws:
                        logger.warning("WebSocket closed unexpectedly")
                    break

        # Main connection loop with reconnection support
        ws: aiohttp.ClientWebSocketResponse | None = None

        while True:
            try:
                ws = await self._connect_ws()
                tasks = [
                    asyncio.create_task(send_task(ws)),
                    asyncio.create_task(recv_task(ws)),
                ]
                tasks_group = asyncio.gather(*tasks)
                wait_reconnect_task = asyncio.create_task(self._reconnect_event.wait())

                try:
                    done, _ = await asyncio.wait(
                        (tasks_group, wait_reconnect_task),
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    for task in done:
                        if task != wait_reconnect_task:
                            task.result()

                    if wait_reconnect_task not in done:
                        break  # Normal completion

                    # Reconnection requested
                    self._reconnect_event.clear()
                    logger.debug("Reconnecting due to options update")

                finally:
                    await utils.aio.gracefully_cancel(*tasks)

            except asyncio.TimeoutError as e:
                logger.error("MiniMax STT connection timeout")
                raise APITimeoutError("Connection timeout") from e
            except aiohttp.ClientResponseError as e:
                logger.error("MiniMax STT HTTP error: %s %s", e.status, e.message)
                raise APIStatusError(
                    message=e.message,
                    status_code=e.status,
                    request_id=None,
                    body=None,
                ) from e
            except aiohttp.ClientError as e:
                logger.error("MiniMax STT connection error: %s", e)
                raise APIConnectionError("Connection failed") from e
            finally:
                if ws:
                    await ws.close()
                    self._ws = None

    async def _connect_ws(self) -> aiohttp.ClientWebSocketResponse:
        """Establish WebSocket connection to MiniMax ASR API."""
        # Build connection parameters
        params: dict[str, Any] = {
            "model": self._opts.model,
            "language": self._opts.language,
            "sample_rate": str(self._opts.sample_rate),
            "encoding": self._opts.encoding,
        }

        if self._opts.vad_enabled:
            params["vad"] = "true"
            params["vad_threshold"] = str(self._opts.vad_threshold)
            params["vad_min_silence_ms"] = str(self._opts.vad_min_silence_duration_ms)

        # Build URL with query parameters
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        ws_url = f"{self._opts.base_url}?{query_string}"

        # Prepare headers with authentication
        headers = {
            "Authorization": f"Bearer {self._opts.api_key}",
            "Content-Type": "application/json",
        }

        if self._opts.group_id:
            headers["X-MiniMax-Group-Id"] = self._opts.group_id

        logger.debug("Connecting to MiniMax ASR WebSocket: %s", ws_url)

        try:
            ws = await asyncio.wait_for(
                self._session.ws_connect(ws_url, headers=headers),
                self._conn_options.timeout,
            )
            self._ws = ws
            logger.info("Connected to MiniMax ASR WebSocket")

            # Send initial configuration message if needed
            # (Some APIs require a "start" message)
            config_msg = {
                "type": "config",
                "model": self._opts.model,
                "language": self._opts.language,
                "sample_rate": self._opts.sample_rate,
                "encoding": self._opts.encoding,
            }
            await ws.send_str(json.dumps(config_msg))

            return ws

        except asyncio.TimeoutError as e:
            raise APITimeoutError("WebSocket connection timeout") from e
        except aiohttp.ClientResponseError as e:
            raise APIStatusError(
                message=str(e),
                status_code=e.status,
                request_id=None,
                body=None,
            ) from e

    async def _send_audio_frame(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        frame: utils.audio.AudioFrame,
    ) -> None:
        """Send an audio frame to the WebSocket.

        Audio is base64-encoded and wrapped in a JSON message.
        """
        audio_bytes = frame.data.tobytes()
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        msg = {
            "type": "audio",
            "data": audio_b64,
        }
        await ws.send_str(json.dumps(msg))

    def _process_message(self, data: dict[str, Any]) -> None:
        """Process a message from the WebSocket.

        Expected message format (adjust based on actual MiniMax API):
        {
            "type": "transcript",
            "text": "recognized text",
            "is_final": true/false,
            "confidence": 0.95,
            "start_time": 0.0,
            "end_time": 1.5
        }
        """
        msg_type = data.get("type", "")

        if msg_type == "transcript":
            text = data.get("text", "")
            is_final = data.get("is_final", False)
            confidence = data.get("confidence", 1.0)

            if not text:
                return

            # Handle speech start
            if not self._speaking and text:
                self._speaking = True
                start_event = stt.SpeechEvent(
                    type=stt.SpeechEventType.START_OF_SPEECH,
                )
                self._event_ch.send_nowait(start_event)

            # Create speech event
            alternatives = [
                stt.SpeechData(
                    language=self._opts.language,
                    text=text,
                    confidence=confidence,
                )
            ]

            if is_final:
                event = stt.SpeechEvent(
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                    alternatives=alternatives,
                )
                self._final_events.append(event)
            else:
                event = stt.SpeechEvent(
                    type=stt.SpeechEventType.INTERIM_TRANSCRIPT,
                    alternatives=alternatives,
                )

            self._event_ch.send_nowait(event)

        elif msg_type == "end_of_speech" or msg_type == "vad_end":
            # Handle speech end
            if self._speaking:
                self._speaking = False
                end_event = stt.SpeechEvent(
                    type=stt.SpeechEventType.END_OF_SPEECH,
                )
                self._event_ch.send_nowait(end_event)
                self._final_events.clear()

        elif msg_type == "error":
            error_msg = data.get("message", "Unknown error")
            logger.error("MiniMax ASR error: %s", error_msg)

        elif msg_type == "close":
            logger.debug("MiniMax ASR session closed")

        else:
            logger.debug("Unknown message type: %s", msg_type)
