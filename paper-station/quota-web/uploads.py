"""Bounded PDF intake. Incoming bytes never become executable content."""
import os
from pathlib import Path
import re
import tempfile
import uuid
from urllib.parse import unquote
from pypdf import PdfReader

MAX_SIZE = 64 * 1024 * 1024

def save_pdf(stream, length, encoded_name, folder):
    if not 0 < length <= MAX_SIZE:
        raise ValueError('每篇 PDF 需在 64 MB 以内')
    name = unquote(encoded_name, encoding='utf-8', errors='strict')
    if (not name or len(name) > 150 or '/' in name or '\\' in name
        or not name.lower().endswith('.pdf') or name.startswith('.')):
        raise ValueError('请选择名称正常的 PDF 文件')
    name = re.sub(r'[<>:"|?*\x00-\x1f]', '_', name)
    stem = Path(name).stem.rstrip('. ')
    if not stem or stem.upper().split('.')[0] in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        raise ValueError('文件名不受支持，请重命名后再上传')
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix='.upload-', suffix='.tmp', delete=False) as out:
            temp = Path(out.name)
            remaining = length
            while remaining:
                data = stream.read(min(65536, remaining))
                if not data:
                    raise ValueError('文件传输中断，请重试')
                out.write(data)
                remaining -= len(data)
        with temp.open('rb') as f:
            if not f.read(1024).lstrip().startswith(b'%PDF-'):
                raise ValueError('文件内容不是 PDF')
        try:
            reader = PdfReader(temp, strict=False)
            if reader.is_encrypted:
                raise ValueError('暂不支持加密 PDF，请先在本地解密')
            pages = len(reader.pages)
            if not pages:
                raise ValueError('PDF 没有可读取页面')
        except ValueError:
            raise
        except Exception:
            raise ValueError('PDF 无法解析，请确认文件完整') from None
        # O_EXCL prevents a concurrent upload from overwriting any existing file.
        while True:
            target = folder / (stem + '.pdf')
            try:
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                stem = stem[:100] + '-' + uuid.uuid4().hex[:8]
        try:
            with os.fdopen(fd, 'wb') as out, temp.open('rb') as source:
                while data := source.read(65536):
                    out.write(data)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {'name': target.name, 'pages': pages, 'bytes': length}
    finally:
        if temp:
            temp.unlink(missing_ok=True)
