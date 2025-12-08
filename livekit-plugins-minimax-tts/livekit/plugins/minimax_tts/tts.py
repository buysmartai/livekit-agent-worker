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

"""MiniMax Text-to-Speech implementation.

This module provides TTS and ChunkedStream classes for
speech synthesis using MiniMax's T2A API over HTTP.

API Reference: https://platform.minimax.io/docs/api-reference/speech-t2a-http
"""

from __future__ import annotations

import asyncio
import io
import os
from dataclasses import dataclass
from typing import AsyncIterator

import aiohttp

from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    tts,
    utils,
)
from livekit.agents.tts import TTSCapabilities

from .log import logger
from .models import (
    DEFAULT_AUDIO_FORMAT,
    DEFAULT_BITRATE,
    DEFAULT_MODEL,
    DEFAULT_PITCH,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SPEED,
    DEFAULT_VOICE_ID,
    DEFAULT_VOLUME,
    MINIMAX_TTS_HTTP_URL,
    MINIMAX_TTS_HTTP_URL_FAST,
    TTSAudioFormat,
    TTSLanguages,
    TTSModels,
)


@dataclass
class TTSOptions:
    """Configuration options for MiniMax TTS."""

    model: str
    voice_id: str
    api_key: str
    base_url: str
    sample_rate: int
    bitrate: int
    audio_format: str
    speed: float
    volume: float
    pitch: int
    language_boost: str | None


class TTS(tts.TTS):
    """MiniMax Text-to-Speech.

    Uses MiniMax's T2A HTTP API for speech synthesis.

    Args:
        model: The TTS model to use. Defaults to "speech-02-turbo".
        voice_id: The voice ID to use. Defaults to "male-qn-qingse".
        api_key: MiniMax API key. Falls back to MINIMAX_API_KEY env var.
        base_url: HTTP base URL for the API. Defaults to standard endpoint.
        sample_rate: Audio sample rate in Hz. Defaults to 32000.
        bitrate: Audio bitrate. Defaults to 128000.
        audio_format: Output audio format (mp3, wav, flac). Defaults to "mp3".
        speed: Speech speed (0.5-2.0). Defaults to 1.0.
        volume: Speech volume (0.1-10.0). Defaults to 1.0.
        pitch: Speech pitch (-12 to 12). Defaults to 0.
        language_boost: Language hint for better recognition. Defaults to None.
        use_fast_endpoint: Use the faster endpoint for reduced latency.
        http_session: Optional aiohttp ClientSession to reuse.
    """

    def __init__(
        self,
        *,
        model: TTSModels | str = DEFAULT_MODEL,
        voice_id: str = DEFAULT_VOICE_ID,
        api_key: str | None = None,
        base_url: str | None = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        bitrate: int = DEFAULT_BITRATE,
        audio_format: TTSAudioFormat | str = DEFAULT_AUDIO_FORMAT,
        speed: float = DEFAULT_SPEED,
        volume: float = DEFAULT_VOLUME,
        pitch: int = DEFAULT_PITCH,
        language_boost: TTSLanguages | str | None = None,
        use_fast_endpoint: bool = False,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the MiniMax TTS instance."""
        super().__init__(
            capabilities=TTSCapabilities(
                streaming=False,  # Use synthesize() mode, framework will auto-wrap with StreamAdapter
            ),
            sample_rate=sample_rate,
            num_channels=1,
        )

        # Resolve API key from environment if not provided
        resolved_api_key = api_key or os.environ.get("MINIMAX_API_KEY")
        if not resolved_api_key:
            raise ValueError(
                "MiniMax API key is required. "
                "Pass it as api_key parameter or set MINIMAX_API_KEY environment variable."
            )

        # Determine base URL
        if base_url:
            resolved_base_url = base_url
        elif use_fast_endpoint:
            resolved_base_url = MINIMAX_TTS_HTTP_URL_FAST
        else:
            resolved_base_url = MINIMAX_TTS_HTTP_URL

        self._opts = TTSOptions(
            model=model,
            voice_id=voice_id,
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            sample_rate=sample_rate,
            bitrate=bitrate,
            audio_format=audio_format,
            speed=speed,
            volume=volume,
            pitch=pitch,
            language_boost=language_boost,
        )

        self._session = http_session

        logger.info(
            f"MiniMax TTS initialized: model={model}, voice_id={voice_id}, "
            f"sample_rate={sample_rate}, audio_format={audio_format}"
        )

    def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @property
    def model(self) -> str:
        return self._opts.model

    @property
    def provider(self) -> str:
        return "minimax"

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = APIConnectOptions(),
    ) -> ChunkedStream:
        """Synthesize speech from text.

        Args:
            text: The text to synthesize.
            conn_options: Connection options for the API request.

        Returns:
            A ChunkedStream that yields audio frames.
        """
        return ChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
            opts=self._opts,
            session=self._ensure_session(),
        )

    async def aclose(self) -> None:
        """Close the TTS instance and release resources."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


class ChunkedStream(tts.ChunkedStream):
    """Chunked stream for MiniMax TTS.

    Handles streaming audio synthesis from MiniMax's T2A API.
    """

    def __init__(
        self,
        *,
        tts: TTS,
        input_text: str,
        conn_options: APIConnectOptions,
        opts: TTSOptions,
        session: aiohttp.ClientSession,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._opts = opts
        self._session = session
        self._output_emitter: tts.AudioEmitter | None = None

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        """Execute the TTS synthesis and emit audio frames.
        
        Args:
            output_emitter: The audio emitter to push audio frames to.
        """
        self._output_emitter = output_emitter
        request_id = utils.shortuuid()
        
        # Initialize the output emitter
        output_emitter.initialize(
            request_id=request_id,
            sample_rate=self._opts.sample_rate,
            num_channels=1,
            mime_type=f"audio/{self._opts.audio_format}",
        )
        
        # Build request body according to MiniMax API spec
        request_body = {
            "model": self._opts.model,
            "text": self._input_text,
            "stream": True,  # Enable streaming
            "stream_options": {
                "exclude_aggregated_audio": True,  # Don't send full audio at end
            },
            "voice_setting": {
                "voice_id": self._opts.voice_id,
                "speed": self._opts.speed,
                "vol": self._opts.volume,
                "pitch": self._opts.pitch,
            },
            "audio_setting": {
                "sample_rate": self._opts.sample_rate,
                "bitrate": self._opts.bitrate,
                "format": self._opts.audio_format,
                "channel": 1,
            },
        }

        # Add language boost if specified
        if self._opts.language_boost:
            request_body["language_boost"] = self._opts.language_boost

        headers = {
            "Authorization": f"Bearer {self._opts.api_key}",
            "Content-Type": "application/json",
        }

        logger.debug(
            f"[{request_id}] Starting TTS synthesis: "
            f"text_len={len(self._input_text)}, model={self._opts.model}"
        )

        try:
            timeout = aiohttp.ClientTimeout(
                total=self._conn_options.timeout,
                connect=10.0,
            )

            async with self._session.post(
                self._opts.base_url,
                json=request_body,
                headers=headers,
                timeout=timeout,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        f"[{request_id}] TTS API error: status={response.status}, "
                        f"body={error_text[:500]}"
                    )
                    raise APIStatusError(
                        message=f"MiniMax TTS API error: {response.status}",
                        status_code=response.status,
                        request_id=request_id,
                        body=error_text,
                    )

                # Process streaming response
                # MiniMax returns hex-encoded audio chunks in streaming mode
                content_type = response.headers.get("Content-Type", "")
                
                if "text/event-stream" in content_type:
                    # Server-Sent Events format
                    await self._process_sse_response(response, request_id)
                elif "application/json" in content_type:
                    # JSON response (might be streaming JSON lines)
                    await self._process_json_response(response, request_id)
                else:
                    # Try to process as raw audio stream
                    await self._process_raw_response(response, request_id)

        except asyncio.TimeoutError as e:
            logger.error(f"[{request_id}] TTS request timeout")
            raise APITimeoutError() from e
        except aiohttp.ClientError as e:
            logger.error(f"[{request_id}] TTS connection error: {e}")
            raise APIConnectionError() from e
        except Exception as e:
            logger.error(f"[{request_id}] TTS unexpected error: {e}", exc_info=True)
            raise

        # Flush the output emitter to signal completion
        output_emitter.flush()
        
        logger.debug(f"[{request_id}] TTS synthesis completed")

    async def _process_sse_response(
        self, response: aiohttp.ClientResponse, request_id: str
    ) -> None:
        """Process Server-Sent Events response."""
        import json

        async for line in response.content:
            line = line.decode("utf-8").strip()
            if not line or line.startswith(":"):
                continue

            if line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                    await self._handle_audio_data(data, request_id)
                except json.JSONDecodeError:
                    logger.warning(f"[{request_id}] Failed to parse SSE data: {data_str[:100]}")

    async def _process_json_response(
        self, response: aiohttp.ClientResponse, request_id: str
    ) -> None:
        """Process JSON streaming response."""
        import json

        buffer = b""
        async for chunk in response.content.iter_any():
            buffer += chunk

            # Try to parse complete JSON objects
            while buffer:
                try:
                    # Find the end of a JSON object
                    decoder = json.JSONDecoder()
                    obj, idx = decoder.raw_decode(buffer.decode("utf-8"))
                    buffer = buffer[idx:].lstrip()
                    if isinstance(buffer, str):
                        buffer = buffer.encode("utf-8")
                    await self._handle_audio_data(obj, request_id)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Incomplete JSON, wait for more data
                    break

        # Process any remaining data
        if buffer:
            try:
                data = json.loads(buffer.decode("utf-8"))
                await self._handle_audio_data(data, request_id)
            except json.JSONDecodeError:
                pass

    async def _process_raw_response(
        self, response: aiohttp.ClientResponse, request_id: str
    ) -> None:
        """Process raw audio stream response."""
        audio_data = await response.read()
        if audio_data:
            await self._emit_audio(audio_data, request_id)

    async def _handle_audio_data(self, data: dict, request_id: str) -> None:
        """Handle audio data from API response."""
        # Check for errors
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code", 0) != 0:
            error_msg = base_resp.get("status_msg", "Unknown error")
            logger.error(f"[{request_id}] TTS API returned error: {error_msg}")
            return

        # Extract audio data
        audio_data = data.get("data", {})
        if not audio_data:
            return

        # Get audio content (hex encoded)
        audio_hex = audio_data.get("audio")
        if audio_hex:
            try:
                audio_bytes = bytes.fromhex(audio_hex)
                await self._emit_audio(audio_bytes, request_id)
            except ValueError as e:
                logger.warning(f"[{request_id}] Failed to decode audio hex: {e}")

    async def _emit_audio(self, audio_bytes: bytes, request_id: str) -> None:
        """Emit audio bytes as frames."""
        if not audio_bytes or not self._output_emitter:
            return

        # Push audio bytes to the output emitter
        # The framework handles audio format conversion (MP3 -> PCM)
        self._output_emitter.push(audio_bytes)
