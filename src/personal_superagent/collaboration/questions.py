from django.db import transaction
from django.utils import timezone
from personal_superagent.intake.services import owned, send
from personal_superagent.intake.models import Conversation
from personal_superagent.execution.lifecycle import StateConflict
from .models import Question


@transaction.atomic
def answer(user, id, data):
    c = Conversation.objects.select_for_update().get(pk=owned(user, id).pk)
    from django.shortcuts import get_object_or_404

    question = get_object_or_404(
        Question.objects.select_for_update(), pk=data["question_id"], conversation=c
    )
    choice = data.get("choice")
    text = (
        data.get("custom", "")
        if choice == 3
        else question.options[choice]
        if isinstance(choice, int) and 0 <= choice < 3
        else None
    )
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
        raise ValueError("请选择或输入回答")
    if question.answered_at:
        if question.answer != text:
            raise StateConflict("问题已回答")
        return
    if c.version != data["version"]:
        raise StateConflict("问题版本冲突")
    question.answer = text
    question.answered_at = timezone.now()
    question.save(update_fields=["answer", "answered_at"])
    send(user, id, {**data, "text": text})
