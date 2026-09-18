import pytest
from fastapi import HTTPException
from app.security import normalize_video_url, safe_filename, validate_source_url


def test_safe_filename_removes_path_characters():
    assert safe_filename('../bad:name?.mp4') == '_bad_name_.mp4'


def test_rejects_non_http_url():
    with pytest.raises(HTTPException):
        validate_source_url('file:///etc/passwd')


def test_normalizes_douyin_jingxuan_modal_link():
    source = 'https://www.douyin.com/jingxuan?modal_id=7683189308064288051'
    assert normalize_video_url(source) == 'https://www.douyin.com/video/7683189308064288051'
