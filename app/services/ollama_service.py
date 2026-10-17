import json
import time
from pathlib import Path

import requests
from flask import current_app


DEFAULT_INSTRUCTIONS = """
You are Proloy, the business assistant for Pagelyne Technologies.

Be natural, concise, helpful, and honest. Answer in the language used by
the customer when possible. Use the supplied business information and
additional instructions. Never invent prices, policies, availability,
contact information, or business capabilities.

Return only valid JSON in this exact structure:
{
  "reply": "Your natural response to the customer",
  "action": {
    "type": "none",
    "data": {}
  }
}

Allowed action types: none, appointment, order, memory.

Use action type "none" for ordinary conversation, greetings, questions,
hypothetical requests, and incomplete requests.

Appointment:
Only propose an appointment action when the customer explicitly wants
to request or book an appointment. Required fields:
customer_name, phone, service, date, time.
Optional fields: email, details.
Date must be YYYY-MM-DD. Never guess missing information. If required
information is missing, ask for it and return action type "none".

Order enquiry:
Only propose an order action when the customer explicitly wants to
make an order enquiry or purchase request.
Required field: item.
At least one of customer_name, phone, or email is required to save it.
Optional fields: details, quantity.
Never claim an order has been placed or paid.

Customer memory:
Only propose memory when the customer explicitly asks you to remember
or save a non-sensitive detail. Fields: customer_name, phone, email,
memory, consent. Set consent to true only when explicitly requested.
Never store passwords, payment credentials, authentication secrets,
or sensitive personal information.

For action type "none", data must be an empty object.
Never claim an action was saved. The application will validate and save it.
Do not include Markdown fences around the JSON.
"""


class OllamaService:
    @staticmethod
    def _read_markdown(path: Path) -> str:
        if not path.exists():
            current_app.logger.warning(
                "Business instruction file not found: %s", path.name
            )
            return ""

        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            current_app.logger.exception(
                "Could not read instruction file: %s", path.name
            )
            raise RuntimeError(
                f"Could not read business file: {path.name}"
            ) from exc

    @classmethod
    def build_system_prompt(cls) -> str:
        business_dir = Path(
            current_app.config["BUSINESS_DATA_DIRECTORY"]
        )

        business_info = cls._read_markdown(
            business_dir / "business_info.md"
        )
        ai_instructions = cls._read_markdown(
            business_dir / "ai_instructions.md"
        )

        sections = [
            DEFAULT_INSTRUCTIONS,
            "\n\nBUSINESS INFORMATION:\n",
            business_info or "No business information configured.",
            "\n\nADDITIONAL AI INSTRUCTIONS:\n",
            ai_instructions or "No additional instructions configured.",
        ]

        prompt = "\n".join(sections)

        # Avoid accidentally sending an enormous prompt to a small local model.
        max_prompt_chars = 18000
        if len(prompt) > max_prompt_chars:
            current_app.logger.warning(
                "System prompt truncated from %s to %s characters.",
                len(prompt),
                max_prompt_chars,
            )
            prompt = prompt[:max_prompt_chars]

        current_app.logger.info(
            "System prompt prepared: %s characters.", len(prompt)
        )
        return prompt

    @staticmethod
    def _normalize_messages(messages):
        normalized = []

        for message in messages:
            if not isinstance(message, dict):
                continue

            role = message.get("role")
            content = message.get("content", "")

            if role not in ("user", "assistant"):
                continue
            if not isinstance(content, str):
                continue

            item = {
                "role": role,
                "content": content[:4000],
            }

            images = message.get("images")
            if role == "user" and isinstance(images, list):
                valid_images = [
                    image
                    for image in images[:1]
                    if isinstance(image, str)
                    and 0 < len(image) <= 5_000_000
                ]
                if valid_images:
                    item["images"] = valid_images

            normalized.append(item)

        # Keep only the most recent six messages to reduce context load.
        return normalized[-6:]

    @classmethod
    def chat(cls, messages):
        base_url = current_app.config["OLLAMA_BASE_URL"].rstrip("/")
        model = current_app.config["OLLAMA_MODEL"]
        timeout = int(current_app.config["OLLAMA_TIMEOUT"])

        normalized_messages = cls._normalize_messages(messages)

        if not normalized_messages:
            raise ValueError("At least one valid chat message is required.")

        start = time.monotonic()
        current_app.logger.info(
            "Chat request started. Model=%s, messages=%s",
            model,
            len(normalized_messages),
        )

        system_prompt = cls.build_system_prompt()
        ollama_messages = [
            {"role": "system", "content": system_prompt},
            *normalized_messages,
        ]

        payload = {
            "model": model,
            "messages": ollama_messages,
            "stream": False,
            "format": "json",
            "keep_alive": "10m",
            "options": {
                "temperature": 0.2,
                "num_ctx": 4096,
                "num_predict": 256,
            },
        }

        try:
            current_app.logger.info(
                "Sending request to Ollama: %s/api/chat",
                base_url,
            )

            response = requests.post(
                f"{base_url}/api/chat",
                json=payload,
                timeout=(10, timeout),
            )

            current_app.logger.info(
                "Ollama responded with HTTP %s after %.2f seconds.",
                response.status_code,
                time.monotonic() - start,
            )

            response.raise_for_status()
            ollama_result = response.json()

        except requests.Timeout as exc:
            current_app.logger.exception(
                "Ollama timed out after %.2f seconds.",
                time.monotonic() - start,
            )
            raise RuntimeError(
                "The AI response timed out. Please try a shorter message."
            ) from exc

        except requests.RequestException as exc:
            current_app.logger.exception(
                "Ollama request failed after %.2f seconds.",
                time.monotonic() - start,
            )
            raise RuntimeError(
                "Could not reach Ollama. Verify the Ollama server URL "
                "and confirm that the configured model is available."
            ) from exc

        except (ValueError, json.JSONDecodeError) as exc:
            current_app.logger.exception(
                "Ollama returned an invalid HTTP/JSON response."
            )
            raise RuntimeError(
                "Ollama returned an invalid response. Please try again."
            ) from exc

        content = ollama_result.get("message", {}).get("content", "")

        try:
            result = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            current_app.logger.warning(
                "Model response was not valid JSON. Content length=%s",
                len(content) if isinstance(content, str) else 0,
            )
            return {
                "reply": (
                    content.strip()
                    if isinstance(content, str) and content.strip()
                    else "Sorry, I couldn't prepare a response. Please try again."
                ),
                "action": {"type": "none", "data": {}},
            }

        reply = result.get("reply")
        action = result.get("action")

        if not isinstance(reply, str) or not reply.strip():
            reply = "Hello! How can I help you today?"

        if not isinstance(action, dict):
            action = {}

        action_type = action.get("type", "none")
        action_data = action.get("data", {})

        if action_type not in ("none", "appointment", "order", "memory"):
            action_type = "none"

        if not isinstance(action_data, dict):
            action_data = {}

        if action_type == "none":
            action_data = {}

        current_app.logger.info(
            "Chat completed in %.2f seconds.",
            time.monotonic() - start,
        )

        return {
            "reply": reply.strip(),
            "action": {
                "type": action_type,
                "data": action_data,
            },
        }