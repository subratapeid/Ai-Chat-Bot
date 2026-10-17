
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import current_app


class RecordStoreError(Exception):
    """Raised when a record cannot safely be read or written."""


class RecordStore:
    """
    JSON storage for the local Proloy prototype.

    JSON is suitable for development and low-volume use. For a multi-worker
    production deployment, migrate this service to a transactional database.
    """

    _lock = threading.RLock()

    FILES = {
        "appointments": "appointments.json",
        "orders": "orders.json",
        "customer_memory": "customer_memory.json",
    }

    @classmethod
    def _directory(cls):
        configured = current_app.config.get("RECORDS_DIRECTORY")
        return Path(configured)

    @classmethod
    def _path(cls, record_type):
        if record_type not in cls.FILES:
            raise RecordStoreError("Unsupported record type.")

        return cls._directory() / cls.FILES[record_type]

    @classmethod
    def initialize(cls):
        directory = cls._directory()
        directory.mkdir(parents=True, exist_ok=True)

        with cls._lock:
            for record_type in cls.FILES:
                path = cls._path(record_type)

                if not path.exists():
                    cls._write_records(record_type, [])

    @classmethod
    def _read_records(cls, record_type):
        path = cls._path(record_type)

        if not path.exists():
            cls._write_records(record_type, [])

        try:
            with path.open("r", encoding="utf-8") as file:
                records = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordStoreError(
                f"Cannot safely read {path.name}. "
                "The file may be inaccessible or invalid JSON."
            ) from exc

        if not isinstance(records, list):
            raise RecordStoreError(
                f"{path.name} must contain a JSON array."
            )

        return records

    @classmethod
    def _write_records(cls, record_type, records):
        path = cls._path(record_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".tmp")

        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
                json.dump(
                    records,
                    file,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            os.replace(temporary_path, path)

        except (OSError, TypeError, ValueError) as exc:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

            raise RecordStoreError(
                f"Cannot safely write {path.name}."
            ) from exc

    @staticmethod
    def _clean_text(value, field, max_length=1000, required=False):
        if value is None:
            value = ""

        if not isinstance(value, str):
            raise RecordStoreError(f"{field} must be text.")

        value = value.strip()

        if required and not value:
            raise RecordStoreError(f"{field} is required.")

        if len(value) > max_length:
            raise RecordStoreError(
                f"{field} exceeds {max_length} characters."
            )

        return value

    @staticmethod
    def _timestamp():
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _create(cls, record_type, data):
        with cls._lock:
            records = cls._read_records(record_type)

            record = {
                "id": str(uuid4()),
                "created_at": cls._timestamp(),
                "updated_at": cls._timestamp(),
                **data,
            }

            records.append(record)
            cls._write_records(record_type, records)

            return record

    @classmethod
    def create_appointment(cls, data):
        name = cls._clean_text(data.get("customer_name"), "Customer name", 120, True)
        phone = cls._clean_text(data.get("phone"), "Phone number", 20, True)
        service = cls._clean_text(data.get("service"), "Service", 200, True)
        appointment_date = cls._clean_text(
            data.get("date"), "Appointment date", 10, True
        )
        appointment_time = cls._clean_text(
            data.get("time"), "Appointment time", 20, True
        )
        email = cls._clean_text(data.get("email"), "Email", 254)
        notes = cls._clean_text(data.get("details"), "Details", 2000)

        # Require ISO date format so ambiguous dates are not silently stored.
        try:
            datetime.strptime(appointment_date, "%Y-%m-%d")
        except ValueError as exc:
            raise RecordStoreError(
                "Appointment date must use YYYY-MM-DD format."
            ) from exc

        digits = "".join(character for character in phone if character.isdigit())
        if len(digits) < 10 or len(digits) > 15:
            raise RecordStoreError("Enter a valid phone number.")

        return cls._create(
            "appointments",
            {
                "customer_name": name,
                "phone": phone,
                "email": email,
                "service": service,
                "date": appointment_date,
                "time": appointment_time,
                "details": notes,
                "status": "requested",
                "source": "proloy_chat",
            },
        )

    @classmethod
    def create_order_inquiry(cls, data):
        name = cls._clean_text(data.get("customer_name"), "Customer name", 120)
        phone = cls._clean_text(data.get("phone"), "Phone number", 20)
        email = cls._clean_text(data.get("email"), "Email", 254)
        item = cls._clean_text(data.get("item"), "Product or service", 200, True)
        details = cls._clean_text(data.get("details"), "Order details", 2000)

        if not details:
            details = item

        if not (name or phone or email):
            raise RecordStoreError(
                "At least one customer contact detail is required "
                "to save an order enquiry."
            )

        return cls._create(
            "orders",
            {
                "customer_name": name,
                "phone": phone,
                "email": email,
                "item": item,
                "details": details,
                "quantity": data.get("quantity"),
                "status": "inquiry",
                "source": "proloy_chat",
            },
        )

    @classmethod
    def save_customer_memory(cls, data):
        name = cls._clean_text(data.get("customer_name"), "Customer name", 120)
        phone = cls._clean_text(data.get("phone"), "Phone number", 20)
        email = cls._clean_text(data.get("email"), "Email", 254)
        memory = cls._clean_text(data.get("memory"), "Memory", 1000, True)

        # Never treat the model's output alone as consent. The caller must
        # confirm that the customer explicitly requested this memory to be saved.
        if data.get("consent") is not True:
            raise RecordStoreError(
                "Explicit customer consent is required to save memory."
            )

        if not (name or phone or email):
            raise RecordStoreError(
                "A customer name, phone number or email is required "
                "to associate this memory with a customer."
            )

        return cls._create(
            "customer_memory",
            {
                "customer_name": name,
                "phone": phone,
                "email": email,
                "memory": memory,
                "consent": True,
                "status": "active",
                "source": "proloy_chat",
            },
        )
