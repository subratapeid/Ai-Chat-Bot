
import re

from flask import Blueprint, current_app, jsonify, request

from app.services.ollama_service import OllamaService
from app.services.record_store import RecordStore, RecordStoreError


chat_bp = Blueprint("chat", __name__)


def _get_user_text(messages):
    return "\n".join(
        message["content"]
        for message in messages
        if message.get("role") == "user"
        and isinstance(message.get("content"), str)
    )


def _matches(pattern, text):
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _clear_action():
    return {"type": "none", "data": {}}


def _execute_action(action, conversation_text, latest_user_text):
    if not isinstance(action, dict):
        return None, None

    action_type = action.get("type", "none")
    data = action.get("data", {})

    if action_type == "none":
        return None, None

    if action_type not in ("appointment", "order", "memory"):
        current_app.logger.warning(
            "Ignoring unsupported AI action type: %s",
            action_type,
        )
        return None, None

    if not isinstance(data, dict):
        return None, (
            "I couldn't validate those details. "
            "Please provide the information again."
        )

    # Appointment request
    if action_type == "appointment":
        explicit_intent = _matches(
            r"\b(appointment|book\s+(?:a|an|my)|"
            r"schedule\s+(?:a|an|my)|arrange\s+(?:a|an|my)|"
            r"meet(?:ing)?\s+with)\b",
            conversation_text,
        )

        if not explicit_intent:
            return None, None

        try:
            record = RecordStore.create_appointment(data)

        except RecordStoreError:
            current_app.logger.exception(
                "Appointment request could not be saved."
            )
            return None, (
                "I couldn't save the appointment request yet. Please provide "
                "your name, phone number, service, date in YYYY-MM-DD format, "
                "and preferred time."
            )

        return (
            {
                "type": "appointment",
                "id": record["id"],
                "status": record["status"],
            },
            "Your appointment request has been recorded. It is pending "
            "confirmation by the business; it is not yet a confirmed booking.",
        )

    # Order enquiry
    if action_type == "order":
        explicit_intent = _matches(
            r"\b(order|purchase|buy|"
            r"place\s+(?:an?\s+)?order|"
            r"order\s+enquiry|order\s+inquiry)\b",
            conversation_text,
        )

        if not explicit_intent:
            return None, None

        try:
            record = RecordStore.create_order_inquiry(data)

        except RecordStoreError:
            current_app.logger.exception(
                "Order enquiry could not be saved."
            )
            return None, (
                "I couldn't save the order enquiry yet. Please provide the "
                "product or service details and at least one contact detail, "
                "such as your name, phone number, or email."
            )

        return (
            {
                "type": "order",
                "id": record["id"],
                "status": record["status"],
            },
            "Your order enquiry has been recorded. The business still needs "
            "to review and confirm it. This does not mean an order has been "
            "placed or paid for.",
        )

    # Customer memory
    if action_type == "memory":
        explicit_request = _matches(
            r"\b(remember|memorize|memorise|"
            r"save\s+(?:this|that|my|the)|"
            r"keep\s+(?:this|that|my)\s+in\s+mind|"
            r"store\s+(?:this|that|my))\b",
            latest_user_text,
        )

        if not explicit_request:
            return None, None

        # Consent is derived from the customer's own latest message,
        # never from the model's consent field.
        data = dict(data)
        data["consent"] = True

        try:
            record = RecordStore.save_customer_memory(data)

        except RecordStoreError:
            current_app.logger.exception(
                "Customer memory could not be saved."
            )
            return None, (
                "I couldn't save that memory yet. Please provide a customer "
                "name, phone number, or email, along with the non-sensitive "
                "detail you want me to remember."
            )

        return (
            {
                "type": "memory",
                "id": record["id"],
                "status": record["status"],
            },
            "I've saved that detail to the customer memory records.",
        )

    return None, None


@chat_bp.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "model": current_app.config["OLLAMA_MODEL"],
    })


@chat_bp.post("/api/chat")
def chat():
    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        return jsonify({
            "error": "A JSON request body is required."
        }), 400

    messages = body.get("messages")

    if not isinstance(messages, list) or not messages:
        return jsonify({
            "error": "At least one message is required."
        }), 400

    if len(messages) > 30:
        return jsonify({
            "error": "Too many messages in one request."
        }), 400

    valid_messages = []

    for message in messages:
        if not isinstance(message, dict):
            continue

        role = message.get("role")
        content = message.get("content", "")

        if role not in ("user", "assistant"):
            continue

        if not isinstance(content, str):
            continue

        normalized = {
            "role": role,
            "content": content[:12000],
        }

        images = message.get("images")

        if role == "user" and isinstance(images, list):
            normalized["images"] = [
                image
                for image in images[:1]
                if isinstance(image, str) and len(image) <= 5_000_000
            ]

        valid_messages.append(normalized)

    if not valid_messages or valid_messages[-1]["role"] != "user":
        return jsonify({
            "error": "The last message must be a user message."
        }), 400

    conversation_text = _get_user_text(valid_messages)

    latest_user_text = next(
        message["content"]
        for message in reversed(valid_messages)
        if message["role"] == "user"
    )

    try:
        result = OllamaService.chat(valid_messages)

        if not isinstance(result, dict):
            raise RuntimeError("The AI returned an invalid response.")

        action = result.get("action", _clear_action())

        record, action_message = _execute_action(
            action,
            conversation_text,
            latest_user_text,
        )

        reply = result.get("reply", "How can I help you today?")

        if not isinstance(reply, str) or not reply.strip():
            reply = "How can I help you today?"

        if action_message:
            reply = f"{reply.strip()}\n\n{action_message}"

        response = {"reply": reply}

        if record:
            response["record"] = record

        return jsonify(response)

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except RuntimeError as exc:
        current_app.logger.error("AI service error: %s", exc)
        return jsonify({
            "error": str(exc)
        }), 503

    except Exception:
        current_app.logger.exception("Chat request failed.")
        return jsonify({
            "error": "An unexpected error occurred while processing your message."
        }), 500
