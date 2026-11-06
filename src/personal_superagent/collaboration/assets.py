"""图片只从本次执行固定目录读取，设备图片通过独立上传校验。"""

import io
import re
import base64
from django.http import FileResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from .models import ImageAsset

NAME = re.compile(r"^[a-f0-9]{32}\.png$")


def directory(attempt):
    from personal_superagent.workflow.checkpoints import checkpoint_dir

    return checkpoint_dir(attempt.pk) / "images"


def validate(content):
    from PIL import Image

    if len(content) > 10 * 1024 * 1024:
        raise ValueError("图片过大")
    with Image.open(io.BytesIO(content)) as image:
        if image.format != "PNG" or image.width * image.height > 25_000_000:
            raise ValueError("图片格式无效")
        image.verify()


def upload(attempt, name, encoded):
    if not NAME.fullmatch(name):
        raise ValueError("图片文件名无效")
    content = base64.b64decode(encoded, validate=True)
    validate(content)
    path = directory(attempt)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = path / name
    if target.is_symlink():
        raise ValueError("图片路径非法")
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError("图片不能覆盖")
    else:
        if len(list(path.glob("*.png"))) >= attempt.input_snapshot.get(
            "policy", {}
        ).get("max_images", 2):
            raise ValueError("图片交付超过授权额度")
        with target.open("xb") as f:
            f.write(content)


def project(attempt, snapshot):
    for asset in snapshot.get("images", []):
        name = asset["name"]
        if not NAME.fullmatch(name):
            raise ValueError("图片文件名无效")
        path = directory(attempt) / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("图片不存在")
        validate(path.read_bytes())
        ImageAsset.objects.get_or_create(attempt=attempt, name=name)


@login_required
def image(request, id):
    asset = get_object_or_404(ImageAsset, pk=id, attempt__task__owner=request.user)
    path = directory(asset.attempt) / asset.name
    if path.is_symlink() or not path.is_file():
        from django.http import Http404

        raise Http404()
    response = FileResponse(
        path.open("rb"),
        content_type="image/png",
        as_attachment=request.GET.get("download") == "1",
        filename=asset.name,
    )
    response["Cache-Control"] = "private, no-store"
    return response
