
import json
from pathlib import Path

import requests
from flask import current_app


DEFAULT_INSTRUCTIONS = """
You are Proloy, the business assistant for Pagelyne Technologies.

Be natural, helpful, concise, and honest. Use the supplied business information
and AI instructions as your reference. Never invent prices, policies, availability,
contact information, or business capabilities.

You can propose one of these actions:
- appointment: a customer explicitly requests an appointment
- order: a customer explicitly requests an order or order enquiry
- memory: a customer explicitly asks you to remember a non-sensitive preference
- none: no record action is requested

Do not propose an action for a hypothetical question or casual conversation.
Never claim a record has been saved. The backend will save records only after
validating your proposed action and the customer's explicit request.

Appointment fields:
customer_name, phone, email, service, date, time, details.
Use YYYY-MM-DD for date. Never guess an ambiguous date or time. If required
details are missing, ask the customer for them and set action.type to "none".

Order enquiry fields:
customer_name, phone, email, item, details, quantity.
Do not claim an order is placed or paid. These records are enquiries only.

Customer memory fields:
customer_name, phone, email, memory, consent.
Only propose memory storage when the customer explicitly asks you to remember
or save a non-sensitive preference or detail. Never store passwords, payment
credentials, authentication secrets, or sensitive personal information.
Set consent to true only when the customer's own message clearly requests saving.

Return ONLY valid JSON with this exact structure:
{
  "reply": "Your natural-language response",
  "action": {
    "type": "none",
    "data": {}
  }
}

The action type must be one of none, appointment, order, memory.
For type none, data must be an empty object.
Do not put Markdown fences around the JSON.
"""


class OllamaService:
    @staticmethod
    def _read_markdown(path: Path) -> str:
        if not path.exists():
            return ""

        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            current_app.logger.exception(
                "Could not read business instruction file: %s",
                path,
            )
            raise RuntimeError(
                f"Could not read required business file: {path.name}"
            ) from exc

    @classmethod
    def build_system_prompt(cls) -> str:
        business_dir = Path(current_app.config["BUSINESS_DATA_DIRECTORY"])

        business_info = cls._read_markdown(
            business_dir / "business_info.md"
        )
        ai_instructions = cls._read_markdown(
            business_dir / "ai_instructions.md"
        )

        sections = [
            DEFAULT_INSTRUCTIONS,
            "\n\n--- BUSINESS INFORMATION ---\n",
            business_info or "No business information has been configured.",
            "\n\n--- ADDITIONAL AI INSTRUCTIONS ---\n",
            ai_instructions or "No additional AI instructions have been configured.",
        ]

        return "\n".join(sections)

    @staticmethod
    def _normalize_messages(messages):
        normalized = []

        for message in messages:
            if not isinstance(message, dict):
                continue

            role = message.get("role")
            if role not in ("user", "assistant"):
                continue

            content = message.get("content", "")
            if not isinstance(content, str):
                continue

            item = {
                "role": role,
                "content": content[:12000],
            }

            images = message.get("images")
            if role == "user" and isinstance(images, list):
                valid_images = [
                    image
                    for image in images[:1]
                    if isinstance(image, str)
                    and len(image) <= 5_000_000
                ]
                if valid_images:
                    item["images"] = valid_images

            normalized.append(item)

        return normalized[-12:]

    @classmethod
    def chat(cls, messages):
        base_url = current_app.config["OLLAMA_BASE_URL"]
        model = current_app.config["OLLAMA_MODEL"]
        timeout = current_app.config["OLLAMA_TIMEOUT"]

        normalized_messages = cls._normalize_messages(messages)

        if not normalized_messages:
            raise ValueError("At least one valid chat message is required.")

        ollama_messages = [
            {
                "role": "system",
                "content": cls.build_system_prompt(),
            },
            *normalized_messages,
        ]

        try:
            response = requests.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": ollama_messages,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.2,
                    },
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()

        except requests.Timeout as exc:
            current_app.logger.warning("Ollama request timed out.")
            raise RuntimeError(
                "The AI took too long to respond. Please try again."
            ) from exc

        except requests.RequestException as exc:
            current_app.logger.exception("Ollama API request failed.")
            raise RuntimeError(
                "Could not connect to Ollama. Check that Ollama is running "
                "and the configured model is available."
            ) from exc

        content = payload.get("message", {}).get("content", "")

        try:
            result = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            current_app.logger.warning(
                "Ollama returned a response that was not valid JSON."
            )
            return {
                "reply": (
                    "I couldn't process that response properly. "
                    "Could you please try again?"
                ),
                "action": {"type": "none", "data": {}},
            }

        reply = result.get("reply")
        action = result.get("action", {})

        if not isinstance(reply, str) or not reply.strip():
            reply = "How can I help you today?"

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

        return {
            "reply": reply.strip(),
            "action": {
                "type": action_type,
                "data": action_data,
            },
        }
