import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Device, Pairing


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_pairing(user) -> str:
    code = secrets.token_urlsafe(24)
    Pairing.objects.create(
        owner=user,
        code_hash=digest(code),
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    return code


@transaction.atomic
def pair(code: str, name: str) -> tuple[Device, str]:
    record = (
        Pairing.objects.select_for_update()
        .filter(code_hash=digest(code), consumed_at=None, expires_at__gt=timezone.now())
        .first()
    )
    if record is None:
        raise ValueError("绑定码无效、已使用或已过期")
    token = secrets.token_urlsafe(32)
    device = Device.objects.create(
        owner=record.owner, name=name, token_hash=digest(token)
    )
    record.consumed_at = timezone.now()
    record.save(update_fields=["consumed_at"])
    return device, token


def authenticate(request) -> Device | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or len(header) > 200:
        return None
    return Device.objects.filter(token_hash=digest(header[7:]), revoked_at=None).first()
